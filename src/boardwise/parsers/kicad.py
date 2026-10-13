"""KiCad projects → boardwise models (R3, the second host).

A KiCad project is three text files, and this module reads two of them
without KiCad being installed:

* ``.kicad_sch`` → :class:`~boardwise.core.model.DesignModel` (the schematic
  view, which the 011-family rules are written against);
* ``.kicad_pcb`` → :class:`~boardwise.core.geometry.BoardGeometry` plus the
  board's own netlist view (every pad states its net);
* ``.kicad_pro`` is JSON with project settings only — it is used to find the
  other two (same stem, same folder) and nothing else.

Everything here was written against KiCad's public format and **measured**
against KiCad itself, not aligned with the EasyEDA reader by assumption
(R3's red line). The fixture ``tests/fixtures/kicad_min/`` carries KiCad's own
readings next to the files — ``kicad_min.net`` (kicad-cli's netlist) and
``kicad_min.pcbnew.json`` (pcbnew's geometry) — and the tests hold this
module to them. The measured facts this module depends on:

* **The schematic has no nets.** Connectivity is geometric: a symbol's pin
  sits at ``at + mirror(rotate(rot) · (x, −y))`` — library y is up and the
  sheet's is down, the rotation is applied first and the ``mirror x`` /
  ``mirror y`` after it, in sheet coordinates (the other order swaps the pins
  of a ``rot 90`` + ``mirror y`` resistor; measured against kicad-cli).
  Wires connect at their end points; a junction or a label connects to every
  wire that passes through its point; same-named power symbols and global
  labels are one net everywhere, same-named local labels one net on their
  sheet. A wire end on another wire's interior with no junction there is
  *not* a connection — the case is reported, never guessed.
* **Net names** follow KiCad's netlister except for one deliberate change: a
  root-sheet local label is ``/NAME`` in KiCad's netlist and ``NAME`` here,
  because the rules recognise rails by the name the designer typed
  (``+3V3``, ``VBUS``), not by its sheet path. Unnamed nets are
  ``Net-(REF-PadN)`` with the lowest ``(REF, pin)`` member, as KiCad does.
* **The board is explicit.** KiCad 10 ids copper layers 0 (F.Cu), 2 (B.Cu),
  4, 6 … (inner); units are mm with y pointing down. A pad's ``at`` is its
  position in the **footprint's unrotated frame** with its **absolute**
  orientation; a bottom-side footprint is stored already flipped.

**The layer-id bridge.** boardwise's PCB rules speak the EasyEDA layer ids
(top 1, bottom 2, inner 15+, multi-layer 12) — several rules have them as
constants. A KiCad copper layer is therefore *translated* into that numbering
(:func:`_bw_layer`) before a rule sees it: F.Cu → 1, B.Cu → 2, In{n}.Cu → 14+n,
a ``*.Cu`` pad → 12. That is the model's interface, written down here, not a
claim that the two formats agree. Coordinates become mil, y up.

**What is refused, by name** (:class:`KicadFormatError`, which the CLI turns
into exit 2): a hierarchical schematic (``sheet``) and buses — this is the
minimum closed loop, and a reader that silently skipped a sub-sheet would hand
the rules a netlist with parts missing, which reads as a clean board.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..core.geometry import (
    MULTI_LAYER_ID,
    BoardGeometry,
    BoardOutline,
    ComponentPlacement,
    LayerInfo,
    PadGeometry,
    Point,
    PourShape,
    TrackSegment,
    ViaGeometry,
)
from ..core.model import (
    TRUNCATED_BY_DESIGNATOR,
    Component,
    DesignModel,
    Net,
    Pin,
)

__all__ = [
    "KICAD_SUFFIXES",
    "Atom",
    "KicadFormatError",
    "is_kicad_path",
    "kicad_project_files",
    "load_kicad",
    "parse_sexpr",
    "read_kicad_board",
    "read_kicad_board_model",
    "read_kicad_schematic_model",
    "schematic_connectivity",
]

KICAD_SUFFIXES = frozenset({".kicad_pro", ".kicad_sch", ".kicad_pcb"})

#: 1 mm in mil. Every KiCad length is mm; every boardwise length is mil.
MM_TO_MIL = 1.0 / 0.0254

#: Two schematic points closer than this (mm) are the same point. KiCad's own
#: grid is 0.0254 mm (1 mil) at its finest; files carry 4 decimals.
_SNAP = 1e-4


class KicadFormatError(ValueError):
    """A KiCad file this reader cannot turn into a model honestly."""


# ---------------------------------------------------------------------------
# S-expressions
# ---------------------------------------------------------------------------


class Atom(str):
    """A bare token (``yes``, ``smd``, ``0.25``) as opposed to a quoted string."""

    __slots__ = ()


def parse_sexpr(text: str) -> list:
    """Parse one KiCad S-expression document into nested lists.

    Quoted strings come back as ``str`` (escapes ``\\"`` ``\\\\`` ``\\n``
    decoded), bare tokens as :class:`Atom`. Raises :class:`KicadFormatError`
    on unbalanced parentheses or an unterminated string.
    """
    stack: list[list] = [[]]
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c in " \t\r\n":
            i += 1
        elif c == "(":
            stack.append([])
            i += 1
        elif c == ")":
            if len(stack) == 1:
                raise KicadFormatError(f"unbalanced ')' at offset {i}")
            done = stack.pop()
            stack[-1].append(done)
            i += 1
        elif c == '"':
            j = i + 1
            buf: list[str] = []
            while True:
                if j >= n:
                    raise KicadFormatError(f"unterminated string starting at offset {i}")
                ch = text[j]
                if ch == '"':
                    break
                if ch == "\\" and j + 1 < n:
                    buf.append({"n": "\n", "t": "\t", "\\": "\\", '"': '"'}.get(text[j + 1], text[j + 1]))
                    j += 2
                    continue
                buf.append(ch)
                j += 1
            stack[-1].append("".join(buf))
            i = j + 1
        else:
            j = i
            while j < n and text[j] not in ' \t\r\n()"':
                j += 1
            stack[-1].append(Atom(text[i:j]))
            i = j
    if len(stack) != 1 or len(stack[0]) != 1 or not isinstance(stack[0][0], list):
        raise KicadFormatError("not one balanced S-expression document")
    return stack[0][0]


def _kids(node: list, head: str) -> list[list]:
    return [c for c in node if isinstance(c, list) and c and c[0] == head]


def _first(node: list | None, head: str) -> list | None:
    if node is None:
        return None
    for c in node:
        if isinstance(c, list) and c and c[0] == head:
            return c
    return None


def _arg(node: list | None, head: str, index: int = 1, default: Any = None) -> Any:
    child = _first(node, head)
    if child is None or len(child) <= index:
        return default
    return child[index]


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _yes(node: list | None, head: str, default: bool) -> bool:
    value = _arg(node, head)
    if value is None:
        return default
    return str(value) == "yes"


def _properties(node: list) -> dict[str, str]:
    return {str(p[1]): str(p[2]) for p in _kids(node, "property") if len(p) >= 3}


# ---------------------------------------------------------------------------
# project files
# ---------------------------------------------------------------------------


def is_kicad_path(path: str | Path) -> bool:
    return Path(path).suffix.lower() in KICAD_SUFFIXES


def kicad_project_files(path: str | Path) -> tuple[Path | None, Path | None]:
    """``(schematic, board)`` for a KiCad input — siblings with the same stem.

    Either may be ``None`` when the file is not there; the caller decides
    whether the view it was asked for can be served without it.
    """
    path = Path(path)
    stem = path.with_suffix("")
    sch = stem.with_suffix(".kicad_sch")
    pcb = stem.with_suffix(".kicad_pcb")
    return (sch if sch.is_file() else None, pcb if pcb.is_file() else None)


# ---------------------------------------------------------------------------
# component fields
# ---------------------------------------------------------------------------

#: KiCad has no standard field for these; the spellings in common use, matched
#: case-insensitively. A field that is not there leaves the attribute empty.
_LCSC_FIELDS = ("lcsc", "lcsc part", "lcsc part #", "lcsc#", "jlcpcb part #")
_MPN_FIELDS = ("mpn", "manufacturer part number", "manufacturer_part_number", "mfr part #", "mfr. part #")
_MFR_FIELDS = ("manufacturer", "mfr", "manufacturer_name")


def _field(props: dict[str, str], names: tuple[str, ...]) -> str:
    lowered = {key.lower(): value for key, value in props.items()}
    for name in names:
        value = lowered.get(name, "").strip()
        if value and value != "~":
            return value
    return ""


def _footprint_name(lib_id: str) -> str:
    """``Package_TO_SOT_SMD:SOT-223-3_TabPin2`` → ``SOT-223-3_TabPin2``.

    A KiCad footprint id is ``library-nickname:name``; the nickname is where the
    project found it, not what it is. boardwise's footprint readers compare
    names (a package family is read off the name), so the model carries the
    name and keeps the full id in ``props["Footprint"]`` / ``attrs``. Measured:
    with the nickname left on, ``pcb-footprint-consistency`` read U1's family as
    ``to`` (from ``Package_TO_…``) against the board's ``sot``.
    """
    return lib_id.split(":", 1)[1] if ":" in lib_id else lib_id


def _component(uid: str, ref: str, props: dict[str, str]) -> Component:
    return Component(
        uid=uid,
        designator=ref,
        value=props.get("Value", ""),
        footprint=_footprint_name(props.get("Footprint", "")),
        lcsc_part=_field(props, _LCSC_FIELDS),
        manufacturer=_field(props, _MFR_FIELDS),
        mpn=_field(props, _MPN_FIELDS),
        datasheet="" if props.get("Datasheet", "") in ("", "~") else props.get("Datasheet", ""),
        props=dict(props),
    )


def _natural(text: str) -> list:
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", text)]


# ---------------------------------------------------------------------------
# schematic
# ---------------------------------------------------------------------------


@dataclass
class _LibPin:
    number: str
    name: str
    etype: str
    x: float
    y: float
    unit: int
    style: int


@dataclass
class _Placed:
    """One placed symbol, with its pins already in sheet coordinates."""

    uuid: str
    lib_id: str
    ref: str
    props: dict[str, str]
    is_power: bool
    pins: list[tuple[_LibPin, tuple[float, float]]] = field(default_factory=list)


def _lib_symbols(tree: list) -> dict[str, list]:
    lib = _first(tree, "lib_symbols")
    return {str(s[1]): s for s in _kids(lib, "symbol")} if lib is not None else {}


def _resolve(name: str, lib: dict[str, list], seen: tuple[str, ...] = ()) -> list:
    """A library symbol with ``extends`` resolved against the same table."""
    sym = lib.get(name)
    if sym is None:
        raise KicadFormatError(f"symbol {name!r} is placed but not in the schematic's lib_symbols")
    parent = _arg(sym, "extends")
    if parent is None:
        return sym
    if parent in seen:
        raise KicadFormatError(f"symbol {name!r}: circular extends")
    prefix = name.split(":", 1)[0] + ":" if ":" in name else ""
    base = _resolve(prefix + str(parent), lib, seen + (name,))
    return [sym[0], sym[1]] + [c for c in sym[2:] if isinstance(c, list) and c and c[0] == "property"] + [
        c for c in base[2:] if not (isinstance(c, list) and c and c[0] in ("property", "extends"))
    ]


def _lib_pins(sym: list) -> list[_LibPin]:
    pins: list[_LibPin] = []
    for unit in _kids(sym, "symbol"):
        match = re.search(r"_(\d+)_(\d+)$", str(unit[1]))
        unit_no, style = (int(match.group(1)), int(match.group(2))) if match else (0, 0)
        for pin in _kids(unit, "pin"):
            at = _first(pin, "at") or [None, 0, 0]
            name = str(_arg(pin, "name", default=""))
            pins.append(_LibPin(
                number=str(_arg(pin, "number", default="")),
                name="" if name == "~" else name,
                etype=str(pin[1]) if len(pin) > 1 and not isinstance(pin[1], list) else "",
                x=_num(at[1]), y=_num(at[2]), unit=unit_no, style=style,
            ))
    return pins


def _sheet_point(at: tuple[float, float], rot: float, mirror: str, x: float, y: float) -> tuple[float, float]:
    """Library point → sheet point (measured; see the module docstring)."""
    y = -y
    r = math.radians(rot)
    sx = x * math.cos(r) + y * math.sin(r)
    sy = -x * math.sin(r) + y * math.cos(r)
    if mirror == "x":
        sy = -sy
    elif mirror == "y":
        sx = -sx
    return (round(at[0] + sx, 4), round(at[1] + sy, 4))


def _key(x: float, y: float) -> tuple[int, int]:
    return (round(x / _SNAP), round(y / _SNAP))


class _UnionFind:
    def __init__(self) -> None:
        self.parent: dict[Any, Any] = {}

    def find(self, item: Any) -> Any:
        self.parent.setdefault(item, item)
        root = item
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[item] != root:
            self.parent[item], item = root, self.parent[item]
        return root

    def union(self, a: Any, b: Any) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def _on_segment(p: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> bool:
    (px, py), (ax, ay), (bx, by) = p, a, b
    cross = (bx - ax) * (py - ay) - (by - ay) * (px - ax)
    length = math.hypot(bx - ax, by - ay)
    if length <= _SNAP:
        return math.hypot(px - ax, py - ay) <= _SNAP
    if abs(cross) / length > _SNAP:
        return False
    dot = (px - ax) * (bx - ax) + (py - ay) * (by - ay)
    return -_SNAP <= dot <= length * length + _SNAP


@dataclass
class SchematicConnectivity:
    """What the geometric solve found, per placed pin, before any model is built."""

    placed: list[_Placed]
    #: (placed index, pin number) -> net name
    net_of: dict[tuple[int, str], str]
    #: net name -> how it was named: "power", "global", "local" or "auto"
    named_by: dict[str, str]
    #: wire ends found on another wire's interior with no junction (not joined)
    dangling_tees: list[tuple[float, float]]
    version: str = ""


def schematic_connectivity(path: str | Path) -> SchematicConnectivity:
    """Solve one flat ``.kicad_sch`` into a net per placed pin."""
    path = Path(path)
    tree = parse_sexpr(path.read_text(encoding="utf-8"))
    if not tree or tree[0] != "kicad_sch":
        raise KicadFormatError(f"{path.name}: not a kicad_sch document")
    for head in ("sheet", "bus", "bus_entry"):
        if _kids(tree, head):
            raise KicadFormatError(
                f"{path.name}: {head!r} found — hierarchical schematics and buses are not read yet "
                "(R3 minimum loop: one flat sheet); refusing rather than returning a netlist with "
                "a sub-sheet's parts missing"
            )
    lib = _lib_symbols(tree)
    placed: list[_Placed] = []
    for sym in _kids(tree, "symbol"):
        lib_id = str(_arg(sym, "lib_id", default=""))
        resolved = _resolve(lib_id, lib)
        at = _first(sym, "at") or [None, 0, 0, 0]
        origin = (_num(at[1]), _num(at[2]))
        rot = _num(at[3]) if len(at) > 3 else 0.0
        mirror = str(_arg(sym, "mirror", default=""))
        unit = int(_num(_arg(sym, "unit", default=1), 1))
        style = int(_num(_arg(sym, "body_style", default=_arg(sym, "convert", default=1)), 1))
        props = _properties(sym)
        item = _Placed(
            uuid=str(_arg(sym, "uuid", default="")),
            lib_id=lib_id,
            ref=props.get("Reference", ""),
            props=props,
            is_power=_first(resolved, "power") is not None,
        )
        for pin in _lib_pins(resolved):
            if pin.unit not in (0, unit) or pin.style not in (0, style):
                continue
            item.pins.append((pin, _sheet_point(origin, rot, mirror, pin.x, pin.y)))
        placed.append(item)

    wires = []
    for w in _kids(tree, "wire"):
        pts = [(_num(p[1]), _num(p[2])) for p in _kids(_first(w, "pts") or [], "xy")]
        for a, b in zip(pts, pts[1:]):
            wires.append((a, b))
    junctions = [(_num(_first(j, "at")[1]), _num(_first(j, "at")[2])) for j in _kids(tree, "junction") if _first(j, "at")]
    labels: list[tuple[str, str, tuple[float, float]]] = []
    for kind, scope in (("label", "local"), ("global_label", "global"), ("hierarchical_label", "local")):
        for lab in _kids(tree, kind):
            at = _first(lab, "at")
            if at is not None:
                labels.append((scope, str(lab[1]), (_num(at[1]), _num(at[2]))))

    uf = _UnionFind()
    for a, b in wires:
        uf.union(_key(*a), _key(*b))

    def attach(point: tuple[float, float]) -> None:
        """Join ``point`` to every wire passing through it (end or interior)."""
        for a, b in wires:
            if _on_segment(point, a, b):
                uf.union(_key(*point), _key(*a))

    for j in junctions:
        attach(j)
    for _scope, _name, at in labels:
        attach(at)
    # A wire end (or a pin) touching another wire's *interior* with no junction
    # there: KiCad's own drawing tools put a junction on every such T, so a file
    # without one is either hand-edited or deliberately unjoined. Not joined
    # here, and reported so the reader can tell.
    junction_keys = {_key(*j) for j in junctions}
    contacts = [end for w in wires for end in w]
    contacts += [point for item in placed for _pin, point in item.pins]
    dangling = []
    for end in contacts:
        if _key(*end) in junction_keys:
            continue
        for c, d in wires:
            if _key(*end) in (_key(*c), _key(*d)):
                continue
            if _on_segment(end, c, d):
                dangling.append(end)

    names: dict[Any, list[tuple[int, str, str]]] = {}
    for scope, name, at in labels:
        names.setdefault(uf.find(_key(*at)), []).append((1 if scope == "global" else 2, name, scope))
    for item in placed:
        if not item.is_power:
            continue
        value = item.props.get("Value", "")
        for _pin, point in item.pins:
            names.setdefault(uf.find(_key(*point)), []).append((0, value, "power"))
    # Same-named power / global / local labels are one net (one flat sheet).
    by_name: dict[str, Any] = {}
    for root, entries in list(names.items()):
        for _rank, name, _scope in entries:
            if name in by_name:
                uf.union(by_name[name], root)
            else:
                by_name[name] = root
    merged: dict[Any, list[tuple[int, str, str]]] = {}
    for root, entries in names.items():
        merged.setdefault(uf.find(root), []).extend(entries)

    members: dict[Any, list[tuple[int, str]]] = {}
    for index, item in enumerate(placed):
        if item.is_power:
            continue
        for pin, point in item.pins:
            members.setdefault(uf.find(_key(*point)), []).append((index, pin.number))

    net_of: dict[tuple[int, str], str] = {}
    named_by: dict[str, str] = {}
    for root, pins in members.items():
        entries = merged.get(root, [])
        if entries:
            rank, name, scope = sorted(entries)[0]
        else:
            if len(pins) < 2:
                continue  # an unconnected pin is not a net
            ref, number = min(((placed[i].ref, n) for i, n in pins), key=lambda rn: (_natural(rn[0]), _natural(rn[1])))
            name, scope = f"Net-({ref}-Pad{number})", "auto"
        named_by[name] = scope
        for member in pins:
            net_of[member] = name
    version = str(_arg(tree, "version", default=""))
    return SchematicConnectivity(placed=placed, net_of=net_of, named_by=named_by,
                                 dangling_tees=sorted(set(dangling)), version=version)


def read_kicad_schematic_model(path: str | Path) -> DesignModel:
    """The schematic view of a flat KiCad schematic as a :class:`DesignModel`.

    Repeated designators follow the EasyEDA reader's contract (049 / 105 / 107):
    the **first** placement in the file is the component, the name lands in
    ``duplicate_designators``, a later placement writes no net member, and every
    net it would have joined is filed in ``unproven_nets`` with the
    ``TRUNCATED_BY_DESIGNATOR`` reason — so a rule that would conclude on such a
    net refuses instead.
    """
    path = Path(path)
    solved = schematic_connectivity(path)
    model = DesignModel()
    nets: dict[str, Net] = {}
    dropped_on: dict[str, list[str]] = {}
    seen: dict[str, int] = {}
    for index, item in enumerate(solved.placed):
        if item.is_power or not item.ref or item.ref.startswith("#"):
            continue
        seen[item.ref] = seen.get(item.ref, 0) + 1
        keep = item.ref not in model.components
        if keep:
            component = _component(item.uuid, item.ref, item.props)
            component.props["kicad_lib_id"] = item.lib_id
            model.components[item.ref] = component
        for pin, _point in item.pins:
            net_name = solved.net_of.get((index, pin.number))
            if keep:
                model.components[item.ref].pins.append(Pin(number=pin.number, name=pin.name, net=net_name))
            if net_name is None:
                continue
            net = nets.setdefault(net_name, Net(name=net_name))
            if not keep:
                dropped = dropped_on.setdefault(net_name, [])
                if item.ref not in dropped:
                    dropped.append(item.ref)
                continue
            member = (item.ref, pin.number)
            if member not in net.pins:
                net.pins.append(member)
    model.nets = nets
    model.duplicate_designators = sorted(ref for ref, count in seen.items() if count > 1)
    for name, refs in sorted(dropped_on.items()):
        model.unproven_nets[name] = ()
        model.unproven_reasons[name] = (
            TRUNCATED_BY_DESIGNATOR,
            "the 2nd and later placement of "
            + " and ".join(f"{ref!r} ({seen[ref]} placements on the sheet)" for ref in sorted(refs))
            + " are not in this netlist",
        )
    model.raw = {
        "source": "kicad-schematic",
        "file": str(path),
        "kicadVersion": solved.version,
        "netNamedBy": dict(sorted(solved.named_by.items())),
        "danglingTees": [list(p) for p in solved.dangling_tees],
    }
    return model


# ---------------------------------------------------------------------------
# board
# ---------------------------------------------------------------------------


@dataclass
class _Layers:
    """KiCad copper layer names → boardwise layer ids (the bridge)."""

    by_name: dict[str, int] = field(default_factory=dict)
    infos: dict[int, LayerInfo] = field(default_factory=dict)

    @property
    def copper(self) -> list[int]:
        return sorted(self.infos)


def _bw_layer(name: str, kind: str) -> tuple[int, str] | None:
    """One KiCad copper layer → ``(boardwise id, layer type)`` (see module docstring)."""
    if name == "F.Cu":
        return 1, "TOP"
    if name == "B.Cu":
        return 2, "BOTTOM"
    match = re.fullmatch(r"In(\d+)\.Cu", name)
    if match:
        return 14 + int(match.group(1)), "PLANE" if kind == "power" else "SIGNAL"
    return None


def _read_layers(tree: list) -> _Layers:
    layers = _Layers()
    for entry in (_first(tree, "layers") or [])[1:]:
        if not isinstance(entry, list) or len(entry) < 3:
            continue
        name, kind = str(entry[1]), str(entry[2])
        mapped = _bw_layer(name, kind)
        if mapped is None:
            continue
        bw, layer_type = mapped
        layers.by_name[name] = bw
        layers.infos[bw] = LayerInfo(layer_id=bw, name=name, layer_type=layer_type)
    return layers


def _copper_of(names: list[str], layers: _Layers) -> list[int]:
    out: set[int] = set()
    for name in names:
        if name in ("*.Cu", "F&B.Cu"):
            out.update(layers.copper if name == "*.Cu" else [lid for lid in (1, 2) if lid in layers.infos])
        elif name in layers.by_name:
            out.add(layers.by_name[name])
    return sorted(out)


def _mil(x_mm: float, y_mm: float) -> Point:
    return Point(x_mm * MM_TO_MIL, -y_mm * MM_TO_MIL)


def _net_name(node: list) -> str | None:
    """``(net "GND")`` (KiCad 10) or ``(net 3 "GND")`` (earlier)."""
    child = _first(node, "net")
    if child is None or len(child) < 2:
        return None
    name = child[-1]
    return str(name) if str(name) else None


_PAD_SHAPES = {"circle": "ELLIPSE", "oval": "OVAL", "rect": "RECT", "roundrect": "RECT",
               "trapezoid": "POLYGON", "custom": "POLYGON", "chamfered_rect": "RECT"}


def _arc_points(start: tuple[float, float], mid: tuple[float, float], end: tuple[float, float], steps: int = 8):
    """A three-point arc as a polyline (KiCad stores arcs as start/mid/end)."""
    (x1, y1), (x2, y2), (x3, y3) = start, mid, end
    d = 2 * (x1 * (y2 - y3) + x2 * (y3 - y1) + x3 * (y1 - y2))
    if abs(d) < 1e-12:
        return [start, end]
    ux = ((x1 * x1 + y1 * y1) * (y2 - y3) + (x2 * x2 + y2 * y2) * (y3 - y1) + (x3 * x3 + y3 * y3) * (y1 - y2)) / d
    uy = ((x1 * x1 + y1 * y1) * (x3 - x2) + (x2 * x2 + y2 * y2) * (x1 - x3) + (x3 * x3 + y3 * y3) * (x2 - x1)) / d
    r = math.hypot(x1 - ux, y1 - uy)
    a1, a2, a3 = (math.atan2(y - uy, x - ux) for x, y in (start, mid, end))

    def ccw(a, b):
        return (b - a) % (2 * math.pi)

    sweep = ccw(a1, a3) if ccw(a1, a2) <= ccw(a1, a3) else -ccw(a3, a1)
    return [(ux + r * math.cos(a1 + sweep * k / steps), uy + r * math.sin(a1 + sweep * k / steps)) for k in range(steps + 1)]


def _pts(node: list | None) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for item in (node or [])[1:]:
        if not isinstance(item, list) or not item:
            continue
        if item[0] == "xy":
            out.append((_num(item[1]), _num(item[2])))
        elif item[0] == "arc":
            s, m, e = (_first(item, k) for k in ("start", "mid", "end"))
            if s and m and e:
                points = _arc_points((_num(s[1]), _num(s[2])), (_num(m[1]), _num(m[2])), (_num(e[1]), _num(e[2])))
                out.extend(points if not out else points[1:])
    return out


def _outline(tree: list) -> BoardOutline | None:
    """The Edge.Cuts outline as one closed polygon, or ``None`` when it does not close."""
    segments: list[tuple[tuple[float, float], tuple[float, float]]] = []
    for kind in ("gr_line", "gr_arc", "gr_rect", "gr_poly", "gr_circle"):
        for shape in _kids(tree, kind):
            if str(_arg(shape, "layer", default="")) != "Edge.Cuts":
                continue
            if kind == "gr_rect":
                (x0, y0), (x1, y1) = ((_num(_first(shape, k)[1]), _num(_first(shape, k)[2])) for k in ("start", "end"))
                return BoardOutline(points=[_mil(x0, y0), _mil(x1, y0), _mil(x1, y1), _mil(x0, y1)])
            if kind == "gr_poly":
                pts = _pts(_first(shape, "pts"))
                if len(pts) >= 3:
                    return BoardOutline(points=[_mil(*p) for p in pts])
                continue
            if kind == "gr_circle":
                c, e = _first(shape, "center"), _first(shape, "end")
                cx, cy, r = _num(c[1]), _num(c[2]), math.hypot(_num(e[1]) - _num(c[1]), _num(e[2]) - _num(c[2]))
                return BoardOutline(points=[_mil(cx + r * math.cos(2 * math.pi * k / 72), cy + r * math.sin(2 * math.pi * k / 72)) for k in range(72)])
            s, e = _first(shape, "start"), _first(shape, "end")
            a, b = (_num(s[1]), _num(s[2])), (_num(e[1]), _num(e[2]))
            if kind == "gr_arc" and _first(shape, "mid"):
                m = _first(shape, "mid")
                pts = _arc_points(a, (_num(m[1]), _num(m[2])), b)
                segments += list(zip(pts, pts[1:]))
            else:
                segments.append((a, b))
    if not segments:
        return None

    def close(p, q):
        return math.hypot(p[0] - q[0], p[1] - q[1]) <= 1e-3

    chain = [segments[0][0], segments[0][1]]
    rest = segments[1:]
    while rest:
        for i, (a, b) in enumerate(rest):
            if close(a, chain[-1]):
                chain.append(b)
            elif close(b, chain[-1]):
                chain.append(a)
            else:
                continue
            rest.pop(i)
            break
        else:
            return None  # a gap: the outline does not close
    if not close(chain[0], chain[-1]):
        return None
    return BoardOutline(points=[_mil(*p) for p in chain[:-1]])


def read_kicad_board(path: str | Path) -> BoardGeometry:
    """One ``.kicad_pcb`` as a :class:`BoardGeometry` (mil, y up, boardwise layer ids)."""
    path = Path(path)
    tree = parse_sexpr(path.read_text(encoding="utf-8"))
    if not tree or tree[0] != "kicad_pcb":
        raise KicadFormatError(f"{path.name}: not a kicad_pcb document")
    layers = _read_layers(tree)
    components: list[ComponentPlacement] = []
    pads: list[PadGeometry] = []
    for fp in _kids(tree, "footprint"):
        at = _first(fp, "at") or [None, 0, 0]
        fx, fy = _num(at[1]), _num(at[2])
        rot = _num(at[3]) if len(at) > 3 else 0.0
        side = layers.by_name.get(str(_arg(fp, "layer", default="F.Cu")))
        props = _properties(fp)
        ref = props.get("Reference", "")
        uid = str(_arg(fp, "uuid", default=""))
        origin = _mil(fx, fy)
        lib_id = str(fp[1]) if len(fp) > 1 and not isinstance(fp[1], list) else ""
        components.append(ComponentPlacement(
            id=uid, designator=ref or None, x=origin.x, y=origin.y, angle=rot, layer_id=side,
            footprint=_footprint_name(lib_id) or None,
            value=props.get("Value") or None, attrs={**props, "kicad_footprint": lib_id},
        ))
        r = math.radians(rot)
        for pad in _kids(fp, "pad"):
            pat = _first(pad, "at") or [None, 0, 0]
            lx, ly = _num(pat[1]), _num(pat[2])
            angle = _num(pat[3]) if len(pat) > 3 else 0.0
            ax = fx + lx * math.cos(r) + ly * math.sin(r)
            ay = fy - lx * math.sin(r) + ly * math.cos(r)
            size = _first(pad, "size") or [None, 0, 0]
            kind = str(pad[2]) if len(pad) > 2 else ""
            shape = str(pad[3]) if len(pad) > 3 else ""
            layer_names = [str(v) for v in (_first(pad, "layers") or [])[1:]]
            copper = _copper_of(layer_names, layers)
            drill = _first(pad, "drill")
            hole_w = hole_h = hole_d = None
            hole_type = ""
            if drill is not None and kind in ("thru_hole", "np_thru_hole"):
                numbers = [_num(v) for v in drill[1:] if not isinstance(v, list) and str(v) != "oval"]
                if "oval" in [str(v) for v in drill[1:]] and len(numbers) >= 2:
                    hole_w, hole_h, hole_type = numbers[0] * MM_TO_MIL, numbers[1] * MM_TO_MIL, "SLOT"
                elif numbers:
                    hole_d = hole_w = hole_h = numbers[0] * MM_TO_MIL
                    hole_type = "ROUND"
            point = _mil(ax, ay)
            pads.append(PadGeometry(
                id=str(_arg(pad, "uuid", default="")),
                component=ref or None,
                component_id=uid,
                pin_number=str(pad[1]) if len(pad) > 1 else None,
                net=_net_name(pad),
                layer_id=MULTI_LAYER_ID if "*.Cu" in layer_names or kind == "thru_hole" else (copper[0] if copper else None),
                effective_layer_ids=copper,
                x=point.x, y=point.y,
                local_x=lx * MM_TO_MIL, local_y=-ly * MM_TO_MIL,
                width=_num(size[1]) * MM_TO_MIL, height=_num(size[2]) * MM_TO_MIL,
                shape=_PAD_SHAPES.get(shape, shape.upper()),
                angle=angle,
                hole_diameter=hole_d, hole_width=hole_w, hole_height=hole_h, hole_type=hole_type,
                plated=kind == "thru_hole",
            ))
    tracks: list[TrackSegment] = []
    for seg in _kids(tree, "segment"):
        s, e = _first(seg, "start"), _first(seg, "end")
        tracks.append(TrackSegment(
            id=str(_arg(seg, "uuid", default="")), net=_net_name(seg),
            layer_id=layers.by_name.get(str(_arg(seg, "layer", default=""))),
            start=_mil(_num(s[1]), _num(s[2])), end=_mil(_num(e[1]), _num(e[2])),
            width=_num(_arg(seg, "width")) * MM_TO_MIL,
        ))
    for arc in _kids(tree, "arc"):
        s, m, e = (_first(arc, k) for k in ("start", "mid", "end"))
        pts = _arc_points((_num(s[1]), _num(s[2])), (_num(m[1]), _num(m[2])), (_num(e[1]), _num(e[2])))
        for i, (a, b) in enumerate(zip(pts, pts[1:])):
            tracks.append(TrackSegment(
                id=f"{_arg(arc, 'uuid', default='')}#{i}", net=_net_name(arc),
                layer_id=layers.by_name.get(str(_arg(arc, "layer", default=""))),
                start=_mil(*a), end=_mil(*b), width=_num(_arg(arc, "width")) * MM_TO_MIL,
            ))
    vias: list[ViaGeometry] = []
    for via in _kids(tree, "via"):
        at = _first(via, "at")
        names = [str(v) for v in (_first(via, "layers") or [])[1:]]
        span = _copper_of(names, layers)
        # A through via spans every copper layer; a blind/buried one states its
        # pair, and the copper between them is in KiCad's stack order.
        order = ["F.Cu"] + sorted((n for n in layers.by_name if n.startswith("In")), key=_natural) + ["B.Cu"]
        ids = [layers.by_name[n] for n in order if n in layers.by_name]
        if len(span) >= 2 and len(ids) > 2:
            lo, hi = sorted(ids.index(lid) for lid in span if lid in ids)[0], sorted(ids.index(lid) for lid in span if lid in ids)[-1]
            unused = [lid for k, lid in enumerate(ids) if k < lo or k > hi]
        else:
            unused = []
        point = _mil(_num(at[1]), _num(at[2]))
        vias.append(ViaGeometry(
            id=str(_arg(via, "uuid", default="")), net=_net_name(via), x=point.x, y=point.y,
            hole_diameter=_num(_arg(via, "drill")) * MM_TO_MIL,
            via_diameter=_num(_arg(via, "size")) * MM_TO_MIL,
            via_type=next((str(v) for v in via[1:] if str(v) in ("blind", "micro")), ""),
            unused_inner_layers=unused,
        ))
    pours: list[PourShape] = []
    for zone in _kids(tree, "zone"):
        if _first(zone, "keepout") is not None:
            continue  # rule areas are not copper (not read in the minimum loop)
        uid = str(_arg(zone, "uuid", default=""))
        net = _net_name(zone)
        zone_layers = [str(v) for v in (_first(zone, "layers") or _first(zone, "layer") or [])[1:]]
        outline = [_mil(*p) for p in _pts(_first(_first(zone, "polygon"), "pts"))]
        for name in zone_layers:
            if name in layers.by_name and len(outline) >= 3:
                pours.append(PourShape(id=uid, net=net, layer_id=layers.by_name[name], kind="pour", points=outline))
        for filled in _kids(zone, "filled_polygon"):
            lid = layers.by_name.get(str(_arg(filled, "layer", default="")))
            pts = [_mil(*p) for p in _pts(_first(filled, "pts"))]
            if lid is not None and len(pts) >= 3:
                pours.append(PourShape(id=uid, net=net, layer_id=lid, kind="poured", points=pts, poured_from=uid))
    return BoardGeometry(
        source=str(path), name=path.stem, edit_version=str(_arg(tree, "version", default="")),
        layers=layers.infos, components=components, pads=pads, tracks=tracks, vias=vias,
        pours=pours, outline=_outline(tree),
    )


def read_kicad_board_model(path: str | Path, board: BoardGeometry | None = None) -> DesignModel:
    """The board's own netlist view: components from footprints, nets from pads.

    Same repeated-designator contract as the schematic view (first footprint
    kept). Pin names come from the pads' ``pinfunction`` (written by KiCad's
    "update PCB from schematic"); a pad without one has an empty name.
    """
    path = Path(path)
    tree = parse_sexpr(path.read_text(encoding="utf-8"))
    model = DesignModel()
    nets: dict[str, Net] = {}
    seen: dict[str, int] = {}
    dropped_on: dict[str, list[str]] = {}
    for fp in _kids(tree, "footprint"):
        props = _properties(fp)
        ref = props.get("Reference", "")
        if not ref or ref.startswith("#"):
            continue
        seen[ref] = seen.get(ref, 0) + 1
        keep = ref not in model.components
        if keep:
            lib_id = str(fp[1]) if len(fp) > 1 and not isinstance(fp[1], list) else ""
            component = _component(str(_arg(fp, "uuid", default="")), ref, {"Footprint": lib_id, **props})
            model.components[ref] = component
        for pad in _kids(fp, "pad"):
            number = str(pad[1]) if len(pad) > 1 else ""
            if not number:
                continue
            net_name = _net_name(pad)
            if keep and not any(p.number == number for p in model.components[ref].pins):
                model.components[ref].pins.append(Pin(number=number, name=str(_arg(pad, "pinfunction", default="")), net=net_name))
            if not net_name or net_name.startswith("unconnected-"):
                continue
            net = nets.setdefault(net_name, Net(name=net_name))
            if not keep:
                dropped_on.setdefault(net_name, [])
                if ref not in dropped_on[net_name]:
                    dropped_on[net_name].append(ref)
                continue
            if (ref, number) not in net.pins:
                net.pins.append((ref, number))
    model.nets = nets
    model.duplicate_designators = sorted(ref for ref, count in seen.items() if count > 1)
    for name, refs in sorted(dropped_on.items()):
        model.unproven_nets[name] = ()
        model.unproven_reasons[name] = (
            TRUNCATED_BY_DESIGNATOR,
            "the 2nd and later footprint of " + " and ".join(repr(r) for r in sorted(refs)) + " are not in this netlist",
        )
    model.raw = {"source": "kicad-board", "file": str(path)}
    return model


def load_kicad(path: str | Path, *, view: str = "schematic") -> tuple[DesignModel, BoardGeometry | None]:
    """``(model, board)`` for a KiCad input, in the ``_load_model`` contract.

    ``view="schematic"`` reads the ``.kicad_sch`` next to (or named by) ``path``
    and returns no geometry; ``view="pcb"`` reads the ``.kicad_pcb`` and returns
    its netlist view with its geometry. A view whose file is missing is a
    :class:`KicadFormatError` naming the file it looked for.
    """
    path = Path(path)
    sch, pcb = kicad_project_files(path)
    if path.suffix.lower() == ".kicad_pro" and not path.is_file():
        raise KicadFormatError(f"{path}: no such project file")
    if path.suffix.lower() == ".kicad_pro":
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise KicadFormatError(f"{path.name}: not a KiCad project (JSON): {exc}") from exc
    if view == "pcb":
        if pcb is None:
            raise KicadFormatError(f"{path.with_suffix('.kicad_pcb').name}: no board next to {path.name} for the pcb view")
        board = read_kicad_board(pcb)
        return read_kicad_board_model(pcb, board), board
    if sch is None:
        raise KicadFormatError(
            f"{path.with_suffix('.kicad_sch').name}: no schematic next to {path.name}; "
            "for the board's own netlist use --view pcb"
        )
    return read_kicad_schematic_model(sch), None
