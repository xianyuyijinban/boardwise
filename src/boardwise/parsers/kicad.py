"""KiCad projects → boardwise models (R3, the second host).

A KiCad project is three text files, and this module reads two of them
without KiCad being installed:

* ``.kicad_sch`` → :class:`~boardwise.core.model.DesignModel` (the schematic
  view, which the 011-family rules are written against);
* ``.kicad_pcb`` → :class:`~boardwise.core.geometry.BoardGeometry` plus the
  board's own netlist view (every pad states its net);
* ``.kicad_pro`` is JSON. It used to be read for one thing only — finding the
  other two files (same stem, same folder) — and **182** made it a data source
  as well: its ``net_settings`` block carries the project's netclasses
  (``diff_pair_width`` / ``diff_pair_gap``, in mm) plus the net →
  netclass ``netclass_assignments`` map and the ``netclass_patterns`` globs, and
  those land in :class:`~boardwise.core.geometry.NetMeta`
  (:func:`read_project_net_settings` / :func:`apply_net_settings`). The block's
  shape is taken from KiCad's own files and public format documentation, not
  guessed: KiCad 9's project initialiser writes ``net_settings`` with
  ``classes[]`` / ``meta.version 4`` / ``netclass_assignments`` /
  ``netclass_patterns``, which is also the shape KiCad 6–8 projects carry.
  Reading it never refuses a board: a missing file, a broken JSON body or a
  wrong type in any key leaves the net metadata empty rather than failing a
  review over a settings block this reader does not need.

Everything here was written against KiCad's public format and **measured**
against KiCad itself, not aligned with the EasyEDA reader by assumption
(R3's red line). The fixture ``tests/fixtures/kicad_min/`` carries KiCad's own
readings next to the files — ``kicad_min.net`` (kicad-cli's netlist) and
``kicad_min.pcbnew.json`` (pcbnew's geometry) — and the tests hold this
module to them. The measured facts this module depends on:

* **The schematic has no nets.** Connectivity is geometric: a symbol's pin
  sits at ``at + mirror(rotate(rot) · (x, −y))`` — library y is up and the
  sheet's is down, the rotation is applied first and the ``mirror x`` /
  ``mirror y`` after it, in sheet coordinates. **Measured** against kicad-cli
  on the fixture: its one rotated-and-mirrored part (R3, ``4.7k``) is written
  ``(rot 270, mirror x)``, and this order reproduces kicad-cli's netlist pin
  for pin — the other order swaps that part's pins and the test goes red. The
  ``mirror y`` *branch* on its own is **not** oracle-backed: kicad-cli's
  ``sch upgrade`` normalises a ``mirror y`` placement into ``mirror x`` plus a
  half turn, so no KiCad-written file carries one, and the branch rests on a
  synthetic unit assertion only
  (``test_the_pin_transform_is_rotate_then_mirror[90-y-…]``).
  Wires connect at their end points; a junction or a label connects to every
  wire that passes through its point; same-named power symbols and global
  labels are one net everywhere, same-named local labels one net on their
  sheet. A wire end on another wire's interior with no junction there is
  *not* a connection — the case is reported, never guessed.
* **Net names** follow KiCad's netlister except for one deliberate change: a
  root-sheet local label is ``/NAME`` in KiCad's netlist and ``NAME`` here,
  because the rules recognise rails by the name the designer typed
  (``+3V3``, ``VBUS``), not by its sheet path. Unnamed nets are
  ``Net-(REF-PadN)`` with the lowest ``(REF, pin)`` member — kicad-cli's own
  name shape for an unnamed net. (The fixture draws no unnamed net, so this is
  KiCad's documented convention plus this module's own unit assertion, **not**
  a measurement.)
* **A net id alone is read against the file's own net table (191C).** A pad,
  track, via or zone may state a bare ``(net 3)`` — the id without the name
  KiCad 10 writes inline. The name is then looked up in the board's top-level
  ``(net N "NAME")`` table, which is where such a file keeps it. An id that
  table does not name is kept as ``net#3`` and counted
  (:data:`UNNAMED_NET_PREFIX`, :func:`unnamed_net_names`): a ``net#`` shape is
  not one KiCad's netlister ever writes, so it cannot be mistaken for a name
  the designer typed, and the alternative — inventing a plausible name —
  would hand the rules a net that does not exist. The count is disclosed on the
  board entry (``netIdNote``) because nets are recognised *by name*: a board
  whose ids lost their names is a board the name-driven checks cannot see.
  The fixture ``kicad_min/kicad_bare_net.kicad_pcb`` is **hand-written** for
  this shape — no KiCad-written file in this repository carries it — so this
  branch rests on this module's reading of the published grammar, not on a
  measurement against KiCad itself. Before 191C the form was refused by name.
* **The board is explicit.** KiCad 10 ids copper layers 0 (F.Cu), 2 (B.Cu),
  4, 6 … (inner); units are mm with y pointing down. A pad's ``at`` is its
  position in the **footprint's unrotated frame** with its **absolute**
  orientation; a bottom-side footprint is stored already flipped.
* **The stackup is optional and partial (182).** ``(setup (stackup …))`` lists
  the fabricated layers in order — the copper ones by canonical name
  (``"F.Cu"``), the dielectric ones as ``"dielectric 1"`` — each with
  ``(type "copper"|"core"|"prepreg"|…)``, ``(thickness …)`` in mm and, for a
  dielectric, ``(material "FR4")`` / ``(epsilon_r 4.5)`` /
  ``(loss_tangent 0.02)``. The S-expression grammar is KiCad's published one
  ([KiCad board file format](https://dev-docs.kicad.org/en/file-formats/sexpr-pcb/),
  "Stack Up Layer Settings"): the two dielectric columns are **``epsilon_r`` and
  ``loss_tangent``**, not ``permittivity``/``loss_tangent`` — this reader takes
  KiCad's own spelling. Verifying the keys against KiCad rather than against
  EasyEDA's names is the same discipline as the layer-id bridge below.
  A board that states no stackup reads as an empty ``stackup`` list, which is
  the *absent* state :func:`~boardwise.core.measure.read_stackup` already falls
  back from (the ``LAYER`` table).

**The layer-id bridge.** boardwise's PCB rules speak the EasyEDA layer ids
(top 1, bottom 2, inner 15+, multi-layer 12) — several rules have them as
constants. A KiCad copper layer is therefore *translated* into that numbering
(:func:`_bw_layer`) before a rule sees it: F.Cu → 1, B.Cu → 2, In{n}.Cu → 14+n,
a ``*.Cu`` pad → 12. That is the model's interface, written down here, not a
claim that the two formats agree. Coordinates become mil, y up.

**What is refused, by name** (:class:`KicadFormatError`, which the CLI turns
into exit 2): a hierarchical schematic (``sheet``) and buses — this is the
minimum closed loop, and a reader that silently skipped a sub-sheet would hand
the rules a netlist with parts missing, which reads as a clean board. A
**malformed** entity is refused the same way, never with a ``TypeError`` or an
``IndexError``: a geometry element missing its ``start``/``end``/``mid``/
``center``/``at``, a coordinate that is not a number, a wire point, junction or
label without coordinates, a symbol placed but absent from ``lib_symbols``, an
unbalanced S-expression. Every boundary branch of this reader ends in this
class or in ``None``.
"""

from __future__ import annotations

import fnmatch
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
    NetMeta,
    PadGeometry,
    Point,
    PourShape,
    StackupEntry,
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
    "UNNAMED_NET_PREFIX",
    "Atom",
    "KicadFormatError",
    "NetClassDecl",
    "NetSettings",
    "apply_net_settings",
    "is_kicad_path",
    "kicad_project_files",
    "load_kicad",
    "parse_sexpr",
    "read_kicad_board",
    "read_kicad_board_model",
    "read_kicad_schematic_model",
    "read_project_net_settings",
    "schematic_connectivity",
    "unnamed_net_names",
]

KICAD_SUFFIXES = frozenset({".kicad_pro", ".kicad_sch", ".kicad_pcb"})

#: 191C: the name this reader gives a net id the file states **without** a name
#: — a bare ``(net N)`` whose id no ``(net N "NAME")`` row explains. Not a shape
#: KiCad's netlister ever writes, so a ``net#N`` in a report cannot be read as a
#: name the designer typed; see :func:`_net_name` and
#: :func:`unnamed_net_names`.
UNNAMED_NET_PREFIX = "net#"

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


def _need(node: list, head: str, what: str) -> list:
    """``node``'s ``head`` child, or a :class:`KicadFormatError` naming it.

    The named-helper half of this reader's one law: a boundary branch ends in
    :class:`KicadFormatError` (or ``None``), never in the ``TypeError`` /
    ``IndexError`` that ``_first(...)[1]`` raises on a malformed file.
    """
    child = _first(node, head)
    if child is None:
        raise KicadFormatError(f"{what}: no {head!r}")
    return child


def _strict_num(value: Any, what: str, head: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        raise KicadFormatError(f"{what}: {head!r} is not a number: {value!r}") from None


def _coord(node: list, head: str, what: str) -> tuple[float, float]:
    """Two required numbers under ``head``; a missing or bad one refuses."""
    child = _need(node, head, what)
    if len(child) < 3:
        raise KicadFormatError(f"{what}: {head!r} needs two numbers, got {child!r}")
    return _strict_num(child[1], what, head), _strict_num(child[2], what, head)


def _xy_of(item: list, what: str) -> tuple[float, float]:
    """The two numbers of an ``(xy X Y)`` node itself (not a node that has one)."""
    if len(item) < 3:
        raise KicadFormatError(f"{what}: (xy) needs two numbers, got {item!r}")
    return _strict_num(item[1], what, "xy"), _strict_num(item[2], what, "xy")


def _opt_coord(node: list, head: str, what: str) -> tuple[float, float]:
    """Like :func:`_coord`, but an absent ``head`` is ``(0, 0)`` rather than an error."""
    child = _first(node, head)
    if child is None:
        return (0.0, 0.0)
    if len(child) < 3:
        raise KicadFormatError(f"{what}: {head!r} needs two numbers, got {child!r}")
    return _strict_num(child[1], what, head), _strict_num(child[2], what, head)


def _num_arg(node: list, head: str, what: str, default: float = 0.0) -> float:
    """``head``'s first argument as a number.

    Absent → ``default`` (the field is optional); present but unreadable → a
    :class:`KicadFormatError` (a bad number must not read as zero quietly).
    """
    child = _first(node, head)
    if child is None or len(child) < 2:
        return default
    return _strict_num(child[1], what, head)


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
# the project's net settings (.kicad_pro) — 182
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NetClassDecl:
    """One ``net_settings.classes[]`` row: a netclass and its declared diff pair.

    Both sizes are in **mils** — KiCad writes mm and every boardwise length is
    mil, so the conversion happens here, once, at the boundary (the same
    ``MM_TO_MIL`` the pads and tracks are converted with). ``None`` means
    「the class states no usable value」: the key is absent, or it is not a
    number, or it is non-positive (KiCad writes ``0`` for 「not set here」).
    """

    name: str
    diff_pair_width: float | None = None
    diff_pair_gap: float | None = None


@dataclass
class NetSettings:
    """A project's ``net_settings`` block, read leniently (182).

    Three tables, exactly the ones KiCad's own project files carry: the
    classes, the explicit net → netclass assignments (``null`` in a default
    project) and the netclass *patterns* (globs). Every field is optional and
    nothing here raises — see :func:`read_project_net_settings`.
    """

    classes: dict[str, NetClassDecl] = field(default_factory=dict)
    #: net name → netclass, as written (KiCad writes the net's *path* form,
    #: ``"/CAN_H"``, for a net on a child sheet and the bare name is what a
    #: root-sheet net often gets — both forms are tried).
    assignments: dict[str, str] = field(default_factory=dict)
    #: ``(pattern, netclass)`` in **file order**; the first glob that matches a
    #: net wins, which is KiCad's own "first match" reading of the list.
    patterns: list[tuple[str, str]] = field(default_factory=list)

    def netclass_of(self, net: str) -> str | None:
        """The netclass ``net`` resolves to: an assignment first, else a pattern.

        KiCad's own precedence: an explicit assignment beats the pattern list,
        and within the list the first matching entry wins. Both the bare net
        name and its ``"/NAME"`` path form are tried, because a project may
        write either and this reader has no schematic to say which sheet the
        net came from. ``fnmatchcase`` rather than ``fnmatch``: the latter
        lower-cases both sides on Windows, so the same project would resolve
        differently on two machines.
        """
        for candidate in (net, "/" + net):
            klass = self.assignments.get(candidate)
            if klass:
                return klass
        for pattern, klass in self.patterns:
            if fnmatch.fnmatchcase(net, pattern) or fnmatch.fnmatchcase("/" + net, pattern):
                return klass
        return None


def _mil_or_none(value: Any) -> float | None:
    """A declared KiCad length (mm) in mils, or ``None`` when it is not usable."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number * MM_TO_MIL if number > 0 else None


def read_project_net_settings(path: str | Path) -> NetSettings | None:
    """The ``net_settings`` of one ``.kicad_pro``, or ``None`` (182).

    ``None`` covers three situations that all answer the same way, and saying so
    is the point: the file is not there, it is not readable JSON, or it carries
    no ``net_settings`` block. None of them is an error for a *board* review —
    the net metadata is an extra column, and 182's own rule is that an absent
    column stays absent. What is refused is nothing here: an input ``.kicad_pro``
    that is not JSON at all is refused by :func:`load_kicad` before this runs
    (that is a broken *input*, not a missing sidecar).

    Every key is read defensively — a wrong type in any of them drops that one
    table rather than the whole block, so a project written by a newer KiCad
    still yields whatever this reader understands.
    """
    project = Path(path)
    if not project.is_file():
        return None
    try:
        data = json.loads(project.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    block = data.get("net_settings")
    if not isinstance(block, dict):
        return None

    settings = NetSettings()
    for row in block.get("classes") or []:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        settings.classes[name] = NetClassDecl(
            name=name,
            diff_pair_width=_mil_or_none(row.get("diff_pair_width")),
            diff_pair_gap=_mil_or_none(row.get("diff_pair_gap")),
        )
    assignments = block.get("netclass_assignments")
    if isinstance(assignments, dict):
        for net, klass in assignments.items():
            if str(net) and str(klass or "").strip():
                settings.assignments[str(net)] = str(klass).strip()
    for row in block.get("netclass_patterns") or []:
        if not isinstance(row, dict):
            continue
        pattern = str(row.get("pattern") or "").strip()
        klass = str(row.get("netclass") or "").strip()
        if pattern and klass:
            settings.patterns.append((pattern, klass))
    return settings


def apply_net_settings(board: BoardGeometry, settings: NetSettings | None) -> None:
    """Fill ``board.net_meta`` with the netclass each of the board's nets falls in (182).

    A net with **no** resolved netclass gets no row — that is the same
    「nothing was declared」 a net in no class really is, and :func:`netclass_of`
    returning ``None`` cannot be told apart from a class named ``""``. A net
    that resolves to a class the ``classes[]`` list does not describe gets a row
    naming the class with both sizes ``None``: the project declared the
    membership and did not declare the size, which is two different facts and
    the row keeps them apart.

    In place, and only ever additive: ``board.net_meta`` is empty for a KiCad
    board until this runs, and a caller that passes ``None`` leaves it that way.
    """
    if settings is None:
        return
    for net in board.nets:
        klass = settings.netclass_of(net)
        if klass is None:
            continue
        decl = settings.classes.get(klass)
        board.net_meta[net] = NetMeta(
            name=net,
            net_class=klass,
            declared_diff_width=decl.diff_pair_width if decl else None,
            declared_diff_gap=decl.diff_pair_gap if decl else None,
        )


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
    if lib is None:
        return {}
    return {str(s[1]) if len(s) > 1 else "": s for s in _kids(lib, "symbol")}


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


def _lib_pins(sym: list, what: str) -> list[_LibPin]:
    pins: list[_LibPin] = []
    for unit in _kids(sym, "symbol"):
        unit_name = str(unit[1]) if len(unit) > 1 else ""
        match = re.search(r"_(\d+)_(\d+)$", unit_name)
        unit_no, style = (int(match.group(1)), int(match.group(2))) if match else (0, 0)
        for pin in _kids(unit, "pin"):
            x, y = _opt_coord(pin, "at", f"{what}: pin {_arg(pin, 'number', default='')}")
            name = str(_arg(pin, "name", default=""))
            pins.append(_LibPin(
                number=str(_arg(pin, "number", default="")),
                name="" if name == "~" else name,
                etype=str(pin[1]) if len(pin) > 1 and not isinstance(pin[1], list) else "",
                x=x, y=y, unit=unit_no, style=style,
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
        what = f"{path.name}: symbol {lib_id!r}"
        at = _first(sym, "at")
        origin = _opt_coord(sym, "at", what)
        rot = _strict_num(at[3], what, "at") if at is not None and len(at) > 3 else 0.0
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
        for pin in _lib_pins(resolved, what):
            if pin.unit not in (0, unit) or pin.style not in (0, style):
                continue
            item.pins.append((pin, _sheet_point(origin, rot, mirror, pin.x, pin.y)))
        placed.append(item)

    wires = []
    for w in _kids(tree, "wire"):
        pts = [_xy_of(p, f"{path.name}: wire") for p in _kids(_first(w, "pts") or [], "xy")]
        for a, b in zip(pts, pts[1:]):
            wires.append((a, b))
    junctions = [
        _coord(j, "at", f"{path.name}: junction")
        for j in _kids(tree, "junction")
        if _first(j, "at") is not None
    ]
    labels: list[tuple[str, str, tuple[float, float]]] = []
    for kind, scope in (("label", "local"), ("global_label", "global"), ("hierarchical_label", "local")):
        for lab in _kids(tree, kind):
            if _first(lab, "at") is None:
                continue
            what = f"{path.name}: {kind}"
            if len(lab) < 2 or isinstance(lab[1], list):
                raise KicadFormatError(f"{what}: no name")
            labels.append((scope, str(lab[1]), _coord(lab, "at", what)))

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
    # `danglingTees` — wire ends parked on another wire's interior with no
    # junction — rides in `raw` **only**, on purpose: the report's model section
    # is the counts and the nets, not `raw` (cli._model_counts_fields), so a
    # caller that wants them reads `model.raw` here. It is disclosure-only
    # because no rule consumes it yet; the geometric solve deliberately does not
    # join such a T (KiCad's own tools put a junction on every real T), and
    # inventing a connection is exactly what this reader refuses to do.
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


def _stackup_number(value: Any) -> float | None:
    """A stackup number, or ``None`` when the node is absent or unusable (182).

    Deliberately **not** :func:`_strict_num`'s discipline: every stackup column
    is optional metadata (nothing in ``src/`` reads :attr:`StackupEntry.thickness`
    today, and the two dielectric columns are read by no rule yet), so an
    unreadable ``(epsilon_r 4,5)`` must cost that one column and not the whole
    board. Geometry numbers keep the strict path — see the module docstring's
    refusal list.
    """
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _stackup_positive(value: Any) -> float | None:
    """A dielectric column (Er / Df), or ``None`` when the file declared none (182).

    The same rule :func:`boardwise.parsers.epru._positive_or_none` applies on the
    EasyEDA side, and for the same measured reason: KiCad writes ``0`` — not
    ``null`` — for a column the designer left at its default, so ``0`` here
    means 「not declared」, never 「zero permittivity」.
    """
    number = _stackup_number(value)
    return number if number is not None and number > 0 else None


def _read_stackup(tree: list, layers: _Layers) -> list[StackupEntry]:
    """``(setup (stackup …))`` → a :class:`StackupEntry` list, ``[]`` when absent (182).

    **The trade-off this reader has to make.** An EasyEDA ``LAYER_PHYS`` record
    carries a ``layerId``, so a stackup entry's id *is* a boardwise layer id; a
    KiCad ``(stackup)`` entry carries only a name (``"F.Cu"``, ``"dielectric 1"``,
    ``"F.Mask"`` …). Three decisions follow, and they are this function's whole
    interface:

    * a **copper** stackup layer takes the boardwise id the same bridge gives
      every pad and track (:func:`_bw_layer` via the ``layers`` table, so
      ``F.Cu`` → 1, ``B.Cu`` → 2, ``In1.Cu`` → 15) — a stackup entry and the
      copper it describes agree by construction, not by a second mapping;
    * a **non-copper** layer (dielectric, mask, paste, silk) gets the negative id
      ``-(position + 1)``. It has no boardwise id and cannot be given one
      honestly: EasyEDA's dielectric ids (361…) and mask ids (5/6) are *its*
      numbering, and a dielectric wearing ``361`` would be a claim this reader
      cannot make. A negative id cannot collide with any of them, and it keeps
      :func:`~boardwise.core.measure.read_stackup` — which treats an entry as
      copper only when ``board.layers`` has a copper ``LayerInfo`` for its id —
      unable to mistake a dielectric for copper. The cost is that a dielectric
      entry's own ``(type "core"|"prepreg")`` word is **not** carried:
      :class:`StackupEntry` has no slot for it, and 182 adds the two dielectric
      columns only;
    * ``z_index`` is the entry's **position in the stackup**, 0-based, top of
      the board first — KiCad's own order, and the only order the file states.
      It is *not* comparable with an EasyEDA ``zIndex`` (those are 1/1000/9000
      …); as :class:`StackupEntry`'s docstring says, only the ordering means
      anything, never the magnitude.

    ``(thickness …)`` is mm in the file (mils in the model, like every other
    length here). A board with no ``stackup`` node, and a stackup whose ``layer``
    nodes are all malformed, both come back as ``[]`` — the same *absent* state
    ``read_stackup`` falls back from to the ``LAYER`` table.
    """
    setup = _first(tree, "setup")
    stackup = _first(setup, "stackup") if setup is not None else None
    if stackup is None:
        return []

    entries: list[StackupEntry] = []
    for node in _kids(stackup, "layer"):
        if len(node) < 2:
            continue
        name = str(node[1])
        if name == "dielectric" and len(node) > 2 and not isinstance(node[2], list):
            # The published grammar's unquoted form: `(layer dielectric 1 …)`.
            name = f"dielectric {node[2]}"
        if not name:
            continue
        copper_id = layers.by_name.get(name)
        if copper_id is None:
            mapped = _bw_layer(name, str(_arg(node, "type", default="")))
            copper_id = mapped[0] if mapped else None
        thickness = _stackup_number(_arg(node, "thickness"))
        entries.append(StackupEntry(
            layer_id=copper_id if copper_id is not None else -(len(entries) + 1),
            z_index=len(entries),
            material=str(_arg(node, "material", default="") or ""),
            thickness=0.0 if thickness is None else thickness * MM_TO_MIL,
            # KiCad's own key names: `epsilon_r` / `loss_tangent`.
            permittivity=_stackup_positive(_arg(node, "epsilon_r")),
            loss_tangent=_stackup_positive(_arg(node, "loss_tangent")),
        ))
    return entries


def _mil(x_mm: float, y_mm: float) -> Point:
    return Point(x_mm * MM_TO_MIL, -y_mm * MM_TO_MIL)


def _net_id(value: Any) -> int | None:
    """A bare ``(net 3)`` argument as an int, or ``None`` when it is not an id.

    ``Atom`` only: a quoted ``"3"`` is a *name* that happens to be digits (KiCad
    writes one for a net the designer called ``3``), and reading it as an id
    would look it up in the table and drop the name.
    """
    if not isinstance(value, Atom):
        return None
    text = str(value)
    return int(text) if text.isdigit() else None


def _net_table(tree: list) -> dict[int, str]:
    """The board's own top-level ``(net N "NAME")`` table: id → name (191C).

    KiCad 6–9 wrote this table beside the inline name on every pad and track;
    a file whose elements carry only the bare ``(net N)`` form states the names
    here and nowhere else. An id the table gives an **empty** name to —
    ``(net 0 "")``, KiCad's own 「no net」 — is recorded as ``""`` rather than
    dropped, so :func:`_net_name` can tell 「the file says this id has no name」
    apart from 「the file says nothing about this id」: the first is a net that
    is not there, the second is a name that was lost.
    """
    table: dict[int, str] = {}
    for node in _kids(tree, "net"):
        if len(node) < 3:
            continue
        ident = _net_id(node[1])
        if ident is None:
            continue
        name = node[-1]
        table[ident] = "" if isinstance(name, Atom) else str(name)
    return table


def _net_name(
    node: list,
    table: dict[int, str] | None = None,
    unnamed: dict[int, int] | None = None,
) -> str | None:
    """The net one board element states, in any of KiCad's three written forms.

    * ``(net "GND")`` (KiCad 10) — the name inline, no id;
    * ``(net 3 "GND")`` (KiCad 6–9) — the id and the name inline;
    * ``(net 3)`` (191C) — **the id alone**. ``table`` is the file's own
      top-level ``(net N "NAME")`` table (:func:`_net_table`) and the name is
      looked up there. An id the table does not name is kept as ``net#3`` and
      counted in ``unnamed`` (id → how many elements stated it): the file lost
      that name, and inventing a plausible one would hand the rules a net that
      does not exist. An id the table names with the **empty** string is
      ``None`` — the file said this id is not a net, which is a different
      answer from 「the name was lost」 and is not counted.

    A bare argument that is neither an id nor a name (``(net abc)``) is refused
    by name: it is none of the three forms, and reading it as a net called
    ``"abc"`` would be a guess.
    """
    child = _first(node, "net")
    if child is None or len(child) < 2:
        return None
    name = child[-1]
    if not isinstance(name, Atom):
        return str(name) if str(name) else None
    ident = _net_id(name)
    if ident is None:
        raise KicadFormatError(
            f"a bare (net {name}) that is neither a net id nor a quoted name: this reader "
            'targets KiCad 6+ (net "NAME") / (net N "NAME") / (net N)'
        )
    if table is not None and ident in table:
        return table[ident] or None
    if unnamed is not None:
        unnamed[ident] = unnamed.get(ident, 0) + 1
    return f"{UNNAMED_NET_PREFIX}{ident}"


def unnamed_net_names(board: BoardGeometry) -> list[str]:
    """The board's nets whose name the file never stated, sorted (191C).

    Exactly the nets :func:`_net_name` fell back to ``net#N`` for — the shape
    KiCad's netlister cannot write, so a name in this list is this reader's own
    marker for a lost name and not something the designer typed. Empty for a
    board whose every net id the file named, and for every board not read by
    this module (nothing else writes that shape).

    The *count* is this list's length; it rides into the report as the board
    entry's ``netIdNote`` (``engines.pcbreview._board_entry``), because the
    rules that recognise a net by its name cannot see these nets at all.
    """
    return sorted(name for name in board.nets if name.startswith(UNNAMED_NET_PREFIX))


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


def _pts(node: list | None, what: str) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for item in (node or [])[1:]:
        if not isinstance(item, list) or not item:
            continue
        if item[0] == "xy":
            out.append(_xy_of(item, what))
        elif item[0] == "arc":
            s = _coord(item, "start", what)
            m = _coord(item, "mid", what)
            e = _coord(item, "end", what)
            points = _arc_points(s, m, e)
            out.extend(points if not out else points[1:])
    return out


def _outline(tree: list, name: str) -> BoardOutline | None:
    """The Edge.Cuts outline as one closed polygon, or ``None`` when it does not close."""
    segments: list[tuple[tuple[float, float], tuple[float, float]]] = []
    for kind in ("gr_line", "gr_arc", "gr_rect", "gr_poly", "gr_circle"):
        for shape in _kids(tree, kind):
            if str(_arg(shape, "layer", default="")) != "Edge.Cuts":
                continue
            what = f"{name}: {kind} on Edge.Cuts"
            if kind == "gr_rect":
                (x0, y0), (x1, y1) = (_coord(shape, k, what) for k in ("start", "end"))
                return BoardOutline(closed=True, points=[_mil(x0, y0), _mil(x1, y0), _mil(x1, y1), _mil(x0, y1)])
            if kind == "gr_poly":
                pts = _pts(_first(shape, "pts"), what)
                if len(pts) >= 3:
                    return BoardOutline(closed=True, points=[_mil(*p) for p in pts])
                continue
            if kind == "gr_circle":
                (cx, cy), (ex, ey) = (_coord(shape, k, what) for k in ("center", "end"))
                r = math.hypot(ex - cx, ey - cy)
                return BoardOutline(closed=True, points=[_mil(cx + r * math.cos(2 * math.pi * k / 72), cy + r * math.sin(2 * math.pi * k / 72)) for k in range(72)])
            a = _coord(shape, "start", what)
            b = _coord(shape, "end", what)
            if kind == "gr_arc":
                # An arc is always stored as start/mid/end; one without `mid` is
                # malformed, not a straight line — refuse rather than draw a chord.
                pts = _arc_points(a, _coord(shape, "mid", what), b)
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
    return BoardOutline(closed=True, points=[_mil(*p) for p in chain[:-1]])


def read_kicad_board(path: str | Path) -> BoardGeometry:
    """One ``.kicad_pcb`` as a :class:`BoardGeometry` (mil, y up, boardwise layer ids)."""
    path = Path(path)
    tree = parse_sexpr(path.read_text(encoding="utf-8"))
    if not tree or tree[0] != "kicad_pcb":
        raise KicadFormatError(f"{path.name}: not a kicad_pcb document")
    layers = _read_layers(tree)
    # 191C: the board's own net table, read once — every element that states a
    # bare `(net N)` is resolved through it (see `_net_name`).
    net_table = _net_table(tree)
    name = path.name
    components: list[ComponentPlacement] = []
    pads: list[PadGeometry] = []
    for fp in _kids(tree, "footprint"):
        what = f"{name}: footprint"
        at = _first(fp, "at")
        fx, fy = _opt_coord(fp, "at", what)
        rot = _strict_num(at[3], what, "at") if at is not None and len(at) > 3 else 0.0
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
            what = f"{name}: footprint {ref or lib_id} pad {_arg(pad, 'number', default='')}"
            pat = _first(pad, "at")
            lx, ly = _opt_coord(pad, "at", what)
            angle = _strict_num(pat[3], what, "at") if pat is not None and len(pat) > 3 else 0.0
            ax = fx + lx * math.cos(r) + ly * math.sin(r)
            ay = fy - lx * math.sin(r) + ly * math.cos(r)
            sw, sh = _coord(pad, "size", what)
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
                net=_net_name(pad, net_table),
                footprint_layer_id=MULTI_LAYER_ID if "*.Cu" in layer_names or kind == "thru_hole" else (copper[0] if copper else None),
                effective_layer_ids=copper,
                x=point.x, y=point.y,
                local_x=lx * MM_TO_MIL, local_y=-ly * MM_TO_MIL,
                width=sw * MM_TO_MIL, height=sh * MM_TO_MIL,
                shape=_PAD_SHAPES.get(shape, shape.upper()),
                angle=angle,
                hole_diameter=hole_d, hole_width=hole_w, hole_height=hole_h, hole_type=hole_type,
                plated=kind == "thru_hole",
            ))
    tracks: list[TrackSegment] = []
    for seg in _kids(tree, "segment"):
        what = f"{name}: segment"
        a = _coord(seg, "start", what)
        b = _coord(seg, "end", what)
        tracks.append(TrackSegment(
            id=str(_arg(seg, "uuid", default="")), net=_net_name(seg, net_table),
            layer_id=layers.by_name.get(str(_arg(seg, "layer", default=""))),
            start=_mil(*a), end=_mil(*b),
            width=_num_arg(seg, "width", what) * MM_TO_MIL,
        ))
    for arc in _kids(tree, "arc"):
        what = f"{name}: arc"
        pts = _arc_points(_coord(arc, "start", what), _coord(arc, "mid", what), _coord(arc, "end", what))
        for i, (a, b) in enumerate(zip(pts, pts[1:])):
            tracks.append(TrackSegment(
                id=f"{_arg(arc, 'uuid', default='')}#{i}", net=_net_name(arc, net_table),
                layer_id=layers.by_name.get(str(_arg(arc, "layer", default=""))),
                start=_mil(*a), end=_mil(*b), width=_num_arg(arc, "width", what) * MM_TO_MIL,
            ))
    vias: list[ViaGeometry] = []
    for via in _kids(tree, "via"):
        what = f"{name}: via"
        at = _coord(via, "at", what)
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
        point = _mil(*at)
        vias.append(ViaGeometry(
            id=str(_arg(via, "uuid", default="")), net=_net_name(via, net_table), x=point.x, y=point.y,
            hole_diameter=_num_arg(via, "drill", what) * MM_TO_MIL,
            via_diameter=_num_arg(via, "size", what) * MM_TO_MIL,
            via_type=next((str(v) for v in via[1:] if str(v) in ("blind", "micro")), ""),
            unused_inner_layers=unused,
        ))
    pours: list[PourShape] = []
    for zone in _kids(tree, "zone"):
        if _first(zone, "keepout") is not None:
            continue  # rule areas are not copper (not read in the minimum loop)
        uid = str(_arg(zone, "uuid", default=""))
        net = _net_name(zone, net_table)
        zone_layers = [str(v) for v in (_first(zone, "layers") or _first(zone, "layer") or [])[1:]]
        outline = [_mil(*p) for p in _pts(_first(_first(zone, "polygon"), "pts"), f"{name}: zone polygon")]
        for layer_name in zone_layers:
            if layer_name in layers.by_name and len(outline) >= 3:
                pours.append(PourShape(id=uid, net=net, layer_id=layers.by_name[layer_name], kind="pour", points=outline))
        for filled in _kids(zone, "filled_polygon"):
            lid = layers.by_name.get(str(_arg(filled, "layer", default="")))
            pts = [_mil(*p) for p in _pts(_first(filled, "pts"), f"{name}: filled_polygon")]
            if lid is not None and len(pts) >= 3:
                pours.append(PourShape(id=uid, net=net, layer_id=lid, kind="poured", points=pts, poured_from=uid))
    board = BoardGeometry(
        source=str(path), name=path.stem, edit_version=str(_arg(tree, "version", default="")),
        layers=layers.infos, stackup=_read_stackup(tree, layers),
        components=components, pads=pads, tracks=tracks, vias=vias,
        pours=pours, outline=_outline(tree, name),
    )
    # 182: the project's own netclasses, from the sibling `.kicad_pro` (same
    # stem, same folder — the convention `kicad_project_files` already uses).
    # Read here rather than by the caller so every entry point gets it: the
    # PCB runner reads the board through this function directly
    # (`engines.pcbreview._review_units`), never through `load_kicad`, and a
    # netclass that only a `load_kicad` caller could see would be invisible to
    # the rules.
    apply_net_settings(board, read_project_net_settings(path.with_suffix(".kicad_pro")))
    return board


def read_kicad_board_model(path: str | Path, board: BoardGeometry | None = None) -> DesignModel:
    """The board's own netlist view: components from footprints, nets from pads.

    Same repeated-designator contract as the schematic view (first footprint
    kept). Pin names come from the pads' ``pinfunction`` (written by KiCad's
    "update PCB from schematic"); a pad without one has an empty name.

    A pad that states only a bare ``(net N)`` is resolved through the file's own
    net table (:func:`_net_name`); the ids the table does not name are counted in
    ``raw["netIdsWithoutNames"]`` (id → how many pads stated it), which is absent
    — not empty — when the file lost no name. This view reads pads only, so its
    count is the **pads'**; the board's own count is
    :func:`unnamed_net_names` over the board's nets, which is what the report's
    board entry discloses.
    """
    path = Path(path)
    tree = parse_sexpr(path.read_text(encoding="utf-8"))
    net_table = _net_table(tree)
    unnamed: dict[int, int] = {}
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
            net_name = _net_name(pad, net_table, unnamed)
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
    if unnamed:
        model.raw["netIdsWithoutNames"] = {str(ident): count for ident, count in sorted(unnamed.items())}
    return model


def load_kicad(path: str | Path, *, view: str = "schematic") -> tuple[DesignModel, BoardGeometry | None]:
    """``(model, board)`` for a KiCad input, in the ``_load_model`` contract.

    ``view="schematic"`` reads the ``.kicad_sch`` next to (or named by) ``path``
    and returns no geometry; ``view="pcb"`` reads the ``.kicad_pcb`` and returns
    its netlist view with its geometry. A view whose file is missing is a
    :class:`KicadFormatError` naming the file it looked for.

    An **input** ``.kicad_pro`` is still validated here — a project file that is
    not JSON is a broken input and is refused by name. The project's
    ``net_settings`` are read by :func:`read_kicad_board` itself (182), so the
    board this returns carries its netclasses whether or not the caller passed a
    project file; this function's own ``json.loads`` stays the validation.
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
        # `checkup` has no --view and always asks for the schematic
        # (cli.CHECKUP_VIEW), so the old 「use --view pcb」 hint named a flag its
        # caller does not have. The honest next action differs per caller, so
        # the message names both: `review` can ask for the board's own netlist,
        # `checkup` cannot and needs the schematic.
        raise KicadFormatError(
            f"{path.with_suffix('.kicad_sch').name}: no schematic next to {path.name}; "
            "this reader has no board-only view — `review <board> --view pcb` reads the "
            "board's own netlist, while `checkup` (no --view) needs the schematic"
        )
    return read_kicad_schematic_model(sch), None
