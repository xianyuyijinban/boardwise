"""Parser for EasyEDA Pro schematic netlist (``.enet``) files.

Format facts confirmed against real exports (see tests/fixtures):

- The file is UTF-8 JSON. Top level: ``version``, ``components``,
  ``designRule``, ``differentialPair``, ``netClass``, ``equalLengthNetGroup``.
- ``components`` is keyed by an internal uid; the human designator lives in
  ``props["Designator"]``.
- Each pin in ``pinInfoMap`` carries its net in ``info["net"]``.
- Unconnected pins have ``"net": ""`` (empty string, never a missing key);
  the parser normalizes that to ``None``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..core.model import Component, DesignModel, Net, Pin

#: Top-level blocks preserved verbatim into ``DesignModel.raw``.
RAW_TOP_LEVEL_KEYS: tuple[str, ...] = (
    "designRule",
    "differentialPair",
    "netClass",
    "equalLengthNetGroup",
)


def parse_enet(path: str | Path) -> DesignModel:
    """Parse an ``.enet`` file into a :class:`DesignModel`."""
    text = Path(path).read_text(encoding="utf-8")
    data = json.loads(text)
    return enet_dict_to_model(data)


def enet_dict_to_model(data: dict[str, Any]) -> DesignModel:
    """Build a :class:`DesignModel` from an already-decoded ``.enet`` dict."""
    model = DesignModel()

    for uid, comp in data.get("components", {}).items():
        props = comp.get("props") or {}
        designator = props.get("Designator") or uid
        pins: list[Pin] = []
        for pin_key, info in (comp.get("pinInfoMap") or {}).items():
            net = info.get("net")
            if net is not None and not str(net).strip():
                net = None  # unconnected pin: exported as an empty string
            pins.append(
                Pin(
                    number=str(info.get("number", pin_key)),
                    name=str(info.get("name", pin_key)),
                    net=net,
                )
            )
        model.components[designator] = Component(
            uid=uid,
            designator=designator,
            value=props.get("Value", ""),
            footprint=props.get("Footprint", ""),
            lcsc_part=props.get("Supplier Part", ""),
            manufacturer=props.get("Manufacturer", ""),
            mpn=props.get("Manufacturer Part", ""),
            datasheet=props.get("Datasheet", ""),
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
