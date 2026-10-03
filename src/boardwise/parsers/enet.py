"""Parser for EasyEDA Pro schematic netlist (``.enet``) files.

Format facts confirmed against real exports (see tests/fixtures):

- The file is UTF-8 JSON. Top level: ``version``, ``components``,
  ``designRule``, ``differentialPair``, ``netClass``, ``equalLengthNetGroup``.
- ``components`` is keyed by an internal uid; the human designator lives in
  ``props["Designator"]``.
- Each pin in ``pinInfoMap`` carries its net in ``info["net"]``.
- Unconnected pins have ``"net": ""`` (empty string, never a missing key);
  the parser normalizes that to ``None``.

A document that is legal JSON but **not this shape** is refused with
:class:`NetlistShapeError` — the parser's own error type, the precedent
``core.parts.library_from_json`` set with ``PartError`` — and never with a bare
``AttributeError`` from somewhere inside the walk (issue #28: that traceback left
the CLI on exit 1, the code that means "the board has an ERROR", so a machine
could not tell a corrupt input from a defective design).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..core.model import Component, DesignModel, Net, Pin

__all__ = [
    "RAW_TOP_LEVEL_KEYS",
    "NetlistShapeError",
    "components_of",
    "enet_dict_to_model",
    "optional_object",
    "parse_enet",
    "require_object",
    "shape_of",
]


#: Top-level blocks preserved verbatim into ``DesignModel.raw``.
RAW_TOP_LEVEL_KEYS: tuple[str, ...] = (
    "designRule",
    "differentialPair",
    "netClass",
    "equalLengthNetGroup",
)


class NetlistShapeError(ValueError):
    """The decoded document is not the netlist shape this reader expects.

    ``ValueError`` on purpose: every reader of these parsers already handles that
    one class (the CLI turns it into the "cannot be used" exit 2 with one
    ``boardwise:`` line), so the shape gate needs no new catch clause anywhere.

    The message names the **position** of the first thing that is not an object
    ("``components[a].props`` 不是对象…"), because the useful half of the report
    is *where* the document stopped matching — ``.enet`` is written by hand and by
    other tools, so this is a shape a reader meets in practice.

    The type is shared with :mod:`boardwise.parsers.epro2_model` — the board
    view of a ``.epro2`` is a netlist model too, and it reads the same
    dict-shaped fields (a DEVICE's ``attributes``) out of a decoded record
    stream — so both paths refuse a wrong shape with one sentence and one class.
    """


def shape_of(value: Any) -> str:
    """The value's kind, in the words a person reading the error would use."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def require_object(value: Any, where: str) -> dict:
    """``value`` as a mapping, or :class:`NetlistShapeError` naming ``where``."""
    if not isinstance(value, dict):
        raise NetlistShapeError(
            f"{where} 不是对象（期望键值对象，实际是 {shape_of(value)}）"
        )
    return value


def optional_object(value: Any, where: str) -> dict:
    """``value`` when it means "nothing here", else a mapping.

    ``None`` — which is both a missing key's default and an export's explicit
    ``null`` — stays tolerated exactly as it was (``comp.get("props") or {}``):
    a part with no attributes and no pins is a shape real files write, and no
    measurement ever produced a crash from it. Everything else (a list, a number,
    a string) is a structure error, which is what issue #28 measured for
    ``props`` and ``pinInfoMap``.
    """
    if value is None:
        return {}
    return require_object(value, where)


#: Distinguishes "the key is not in the document" from an explicit ``null``.
#: For ``components`` the two are read differently, and the issue's table is why:
#: ``{"components": null}`` is a **broken shape** (one of the six that used to
#: crash), while a document with no ``components`` key at all is an empty netlist
#: — the same tolerance the old ``data.get("components", {})`` had.
_MISSING = object()


def components_of(data: dict) -> dict:
    """The document's ``components`` section: an object, or a missing key = empty."""
    raw = data.get("components", _MISSING)
    if raw is _MISSING:
        return {}
    return require_object(raw, "components")


def _clean(value: Any) -> Any:
    """An explicit JSON ``null`` reads as empty, the way the sibling reader cleans it.

    ``props.get("Value", "")`` defaults only a **missing** key: a key the export
    wrote as ``null`` came through as ``None`` and was then stringified into the
    literal ``"None"`` — a phantom pin number that joins every downstream netlist
    comparison, and an ``AttributeError`` on the first ``value.strip()`` (100 #10).
    ``epro2_model._clean`` maps ``None -> ""`` for the same reason; this is that
    mapping, kept local because the two readers share no module. Nothing else
    changes: a value of any other JSON type is passed through exactly as it was.
    """
    return "" if value is None else value


def parse_enet(path: str | Path) -> DesignModel:
    """Parse an ``.enet`` file into a :class:`DesignModel`."""
    text = Path(path).read_text(encoding="utf-8-sig")
    data = json.loads(text)
    return enet_dict_to_model(data)


def enet_dict_to_model(data: dict[str, Any]) -> DesignModel:
    """Build a :class:`DesignModel` from an already-decoded ``.enet`` dict.

    Raises :class:`NetlistShapeError` — one sentence with the position — when the
    document is not this shape (issue #28). What is *tolerated* is unchanged: a
    ``.enet`` with no ``components`` key at all is an empty netlist (an empty model
    is a coverage question, not a structure one — issue #29), and a component
    without ``props``/``pinInfoMap`` is a part with no attributes and no pins.
    An explicit ``null`` is *not* tolerated for ``components`` (:func:`components_of`).
    """
    data = require_object(data, "(顶层)")
    components = components_of(data)

    model = DesignModel()

    for uid, comp in components.items():
        where = f"components[{uid}]"
        require_object(comp, where)
        props = optional_object(comp.get("props"), f"{where}.props")
        pin_info = optional_object(comp.get("pinInfoMap"), f"{where}.pinInfoMap")
        designator = props.get("Designator") or uid
        pins: list[Pin] = []
        for pin_key, info in pin_info.items():
            require_object(info, f"{where}.pinInfoMap[{pin_key}]")
            net = info.get("net")
            if net is not None and not str(net).strip():
                net = None  # unconnected pin: exported as an empty string
            pins.append(
                Pin(
                    number=str(_clean(info.get("number", pin_key))),
                    name=str(_clean(info.get("name", pin_key))),
                    net=net,
                )
            )
        model.components[designator] = Component(
            uid=uid,
            designator=designator,
            value=_clean(props.get("Value", "")),
            footprint=_clean(props.get("Footprint", "")),
            lcsc_part=_clean(props.get("Supplier Part", "")),
            manufacturer=_clean(props.get("Manufacturer", "")),
            mpn=_clean(props.get("Manufacturer Part", "")),
            datasheet=_clean(props.get("Datasheet", "")),
            props=props,
            pins=pins,
        )

    # Reverse-build the net list from component pins.
    for comp in model.components.values():
        for pin in comp.pins:
            if pin.net is None:
                continue
            net = model.nets.setdefault(pin.net, Net(name=pin.net))
            net.pins.append((comp.designator, pin.number))

    for key in RAW_TOP_LEVEL_KEYS:
        if key in data:
            model.raw[key] = data[key]

    return model
