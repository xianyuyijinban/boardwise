r"""Build a :class:`~boardwise.core.model.DesignModel` from an ``.epro2`` backup.

Where ``.enet`` carries a finished netlist, an ``.epro2`` backup carries a
placed board. This module reconstructs the netlist view of that board so the
same L1 rules can run on both inputs.

How each :class:`~boardwise.core.model.Component` field is filled, and what
is measurably available on the LLC fixture (47 placed components):

===================  ===========================================================  =======
field                source                                                       filled
===================  ===========================================================  =======
``designator``       PCB ``ATTR key="Designator"`` on the COMPONENT               47/47
``value``            DEVICE ``Value`` attribute, else DEVICE title                47/47*
``footprint``        FOOTPRINT document title behind ``ATTR key="Footprint"``     43/47
``lcsc_part``        DEVICE ``Supplier Part``                                     44/47
``manufacturer``     DEVICE ``Manufacturer``                                      44/47
``mpn``              DEVICE ``Manufacturer Part``                                 44/47
``datasheet``        DEVICE ``Datasheet``                                         36/47
``props``            DEVICE attributes + instance attrs + resolve keys            all
``pins``             footprint pads (``pin_number``) and ``PAD_NET`` nets         all
===================  ===========================================================  =======

\* Only 10/47 devices define a ``Value`` attribute; the rest fall back to the
DEVICE title, which is what EasyEDA shows for parts that encode their value
in the device name ("10k", "472M 1KV", "US5M"). It is a display string, not a
parsed quantity.

Left deliberately empty, because the source data is not retained:

- ``Component.role`` / ``Component.block`` — stage-2 intent metadata, still
  unpopulated everywhere.

``Pin.name`` was empty for every ``.epro2`` board until 131a and is now filled.
The names live in SYMBOL documents, which :func:`split_documents` used to drop;
they are kept again and joined through the library — ``placement -> DEVICE ->
DEVICE["Symbol"] -> SYMBOL`` — because the PCB document names no symbol itself
(measured: a placement's attributes are ``Channel ID`` / ``Group ID`` /
``Unique ID`` / ``Value`` and nothing else). Measured coverage after the join:
**122/122, 33/33, 49/49 and 47/47** placements across the four board fixtures,
and 0 pins named on a backup that carries no SYMBOL documents. This is what
revives ``core.architecture._SUPPLY_PIN``, which had been matching nothing here.

The 4/47 components without a footprint name are the same 4 that carry no
``ATTR key="Footprint"``: they have no pad geometry in the backup either, so
they contribute no pins.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..core.model import Component, DesignModel, Net, Pin
from .enet import optional_object, require_object
from .epru import (
    DEVICE_DOC_TYPE,
    FOOTPRINT_DOC_TYPE,
    SYMBOL_DOC_TYPE,
    Document,
    Epro2Source,
    PcbContext,
    collect_pcb_context,
)

__all__ = [
    "DeviceMeta", "device_metas", "footprint_titles", "symbol_pin_names",
    "build_design_model",
]

#: The three ATTR keys that describe one SYMBOL pin. Same three the schematic
#: parser reads (`parsers/schematic.py::_PIN_ATTR_KEYS`); restated here because
#: this module walks SYMBOL records itself and must not import the schematic
#: parser to learn them.
_PIN_ATTR_KEYS = frozenset({"Pin Number", "Pin Name"})


#: DEVICE attribute keys mapped onto the first-class Component fields. The
#: same key names are used by the ``.enet`` export, so a rule cannot tell the
#: two inputs apart.
ATTR_VALUE = "Value"
ATTR_LCSC = "Supplier Part"
ATTR_MANUFACTURER = "Manufacturer"
ATTR_MPN = "Manufacturer Part"
ATTR_DATASHEET = "Datasheet"

#: The DEVICE attribute pointing at the SYMBOL document that names this
#: device's pins. It is the PCB-side model's **only** route to a pin name: a
# placement's own attributes carry no symbol pointer (131a).
ATTR_SYMBOL = "Symbol"

#: EasyEDA writes the string "null" where a library attribute is unset.
_NULL_LITERALS = {"", "null", "NULL", "None", "-"}


@dataclass
class DeviceMeta:
    """The library metadata of one DEVICE document."""

    uuid: str
    title: str = ""
    attributes: dict[str, Any] = field(default_factory=dict)


def _clean(value: Any) -> str:
    """Normalise an attribute value; unset ones (``"null"``) become ``""``."""
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text in _NULL_LITERALS else text


def device_metas(source: Epro2Source) -> dict[str, DeviceMeta]:
    """Return DEVICE document uuid -> its library metadata.

    The two dict-shaped fields it joins are shape-gated (:class:`NetlistShapeError`,
    issue #28): a record stream whose DEVICE ``attributes`` is a list is a damaged
    file, and saying *where* beats an ``AttributeError`` from inside this walk —
    everything downstream reads these attributes as a mapping.
    """
    metas: dict[str, DeviceMeta] = {}
    for document in source.documents_of_type(DEVICE_DOC_TYPE):
        for record in document.records:
            if record.type != "META" or record.body is None or document.uuid is None:
                continue
            where = f"DEVICE {document.uuid}"
            body = require_object(record.body, where)
            metas[document.uuid] = DeviceMeta(
                uuid=document.uuid,
                title=str(body.get("title") or ""),
                attributes=optional_object(body.get("attributes"), f"{where}.attributes"),
            )
    return metas


def footprint_titles(source: Epro2Source) -> dict[str, str]:
    """Return FOOTPRINT document uuid -> its title (the footprint name).

    This is the footprint actually on the board. ``COMPONENT.attrs["Origin
    Footprint"]`` is *not* used for ``Component.footprint``: it records the
    footprint the part was imported with and goes stale when the designer
    swaps it (measured: C1 has ``Origin Footprint``
    ``CAP-TH_L7.9-W3.5-P7.50-D0.5-S2.4`` but sits on
    ``CAP-SMD_L8.0-W6.0-LS11.4``).
    """
    titles: dict[str, str] = {}
    for document in source.documents_of_type(FOOTPRINT_DOC_TYPE):
        if document.uuid is None:
            continue
        for record in document.records:
            if record.type == "META" and record.body is not None:
                titles[document.uuid] = str(record.body.get("title") or "")
    return titles


def symbol_pin_names(source: Epro2Source) -> dict[str, dict[str, str]]:
    """SYMBOL document uuid -> ``pin number -> Pin Name`` (131a).

    This is the **only** place an ``.epro2`` backup writes a pin's name, and
    :func:`build_design_model` joins through the library to fill ``Pin.name`` on
    the PCB side. Measured on the fixtures: a placement's own PCB attributes
    carry ``Channel ID`` / ``Group ID`` / ``Unique ID`` / ``Value`` and **no**
    ``Symbol`` pointer, so the only route is ``placement ->
    DEVICE (placement.attrs["Device"]) -> DEVICE.attributes["Symbol"] ->
    SYMBOL`` — resolved for 122/122, 33/33, 49/49 and 47/47 placements on the
    four board fixtures.

    Two phases, and the order is the point — the same displacement the
    schematic parser documents (``parsers/schematic.py::_commit_symbol``): a
    3.2.186 incremental save appends a changed pin's attributes to the **end**
    of the SYMBOL document, so a pin's attributes are filed by the ``parentId``
    that names it and never by stream position. Every ``PIN`` row is collected
    first, under **both** of its spellings (its own record ``id`` and the
    synthesised ``e<zIndex>`` ref — a V3 file uses either, and on the golden
    board they differ for 12 pin rows), then the attributes are attributed in
    stream order, falling back to the open run only when the ``parentId`` names
    nothing this walk indexed. A field is never overwritten, so nothing already
    placed moves.

    Returns empty for a backup carrying no SYMBOL documents rather than raising:
    names are *extra* evidence, and a board saved before they existed still
    parses.
    """
    names: dict[str, dict[str, str]] = {}
    for document in source.documents_of_type(SYMBOL_DOC_TYPE):
        uuid = document.uuid
        if not uuid:
            continue
        # pin record id -> [number, name]; each PIN is indexed under both
        # spellings, pointing at the same mutable pair.
        slots: dict[str, list[str]] = {}
        indexed: list[list[str]] = []
        for record in document.records:
            body = record.body
            if body is None or record.type != "PIN":
                continue
            pair = ["", ""]
            indexed.append(pair)
            if record.id:
                slots.setdefault(str(record.id), pair)
            slots.setdefault(f"e{body.get('zIndex')}", pair)
        if not indexed:
            continue
        open_slot: list[str] | None = None
        for record in document.records:
            body = record.body
            if body is None:
                continue
            if record.type == "PIN":
                ref = f"e{body.get('zIndex')}"
                open_slot = slots.get(str(record.id or "")) or slots.get(ref)
                continue
            if record.type != "ATTR":
                continue
            key = str(body.get("key") or "")
            if key not in _PIN_ATTR_KEYS:
                continue
            value = str(body.get("value") or "").strip()
            if not value or value == "null":
                continue
            index = 0 if key == "Pin Number" else 1
            slot = slots.get(str(body.get("parentId") or ""))
            if slot is None:
                slot = open_slot
            # First writer wins: a duplicate attribute can only land on a pin
            # that has none, so nothing already placed is displaced.
            if slot is not None and not slot[index]:
                slot[index] = value
        table = {number: name for number, name in indexed if number and name}
        if table:
            names[uuid] = table
    return names


def _pin_sort_key(number: str) -> tuple[int, int | float, str]:
    """Sort pin numbers naturally: ``"2"`` before ``"10"``, letters last."""
    try:
        return (0, int(number), "")
    except ValueError:
        return (1, float("inf"), number)


def build_design_model(
    source: Epro2Source, document: "Document | None" = None
) -> DesignModel:
    """Build the netlist view of an already-decoded :class:`Epro2Source`.

    Uses the cached :class:`PcbContext`, so building geometry and the model
    from one ``.epro2`` walks the PCB document exactly once. Components are
    keyed by designator — the same key :class:`BoardGeometry` exposes through
    ``board.component(designator)`` — so the two views cross-reference.

    ``document`` scopes the read to **one** PCB document (131c). Omitting it
    keeps the historic behaviour exactly: the backup's *first* PCB document,
    cached on the source. So every existing caller is unaffected, and a caller
    that wants one model per board (the PCB review runner does) says which
    document it means. The historic default is the first-document blind spot
    131c's ``run_pcb_review`` closes for the rules, not for the parser — see
    :func:`boardwise.engines.pcbreview.run_pcb_review`.

    Returns an empty model (not an error) when the backup has no PCB
    document, so batch runs survive a backup that was saved before layout.
    """
    model = DesignModel()
    context = (
        source.pcb_context()
        if document is None
        else collect_pcb_context(document, source.footprints(), source.stats)
    )
    if context is None:
        model.raw["project"] = dict(source.project_meta)
        return model

    devices = device_metas(source)
    footprints = footprint_titles(source)
    symbols = symbol_pin_names(source)
    pins_by_component = _group_pins(context, _pin_names_of(context, devices, symbols))

    for placement in context.placements:
        designator = placement.designator or placement.id
        device_uuid = context.device_ids.get(placement.id)
        device = devices.get(device_uuid) if device_uuid else None
        attributes = device.attributes if device is not None else {}

        footprint_uuid = placement.footprint
        footprint_name = (
            footprints.get(footprint_uuid, "") if footprint_uuid else ""
        ) or _clean(placement.attrs.get("Origin Footprint"))

        props: dict[str, Any] = dict(attributes)
        props.update(placement.attrs)
        props["Device"] = device_uuid or ""
        props["DeviceTitle"] = device.title if device is not None else ""
        props["Footprint"] = footprint_uuid or ""
        props["FootprintName"] = footprint_name

        model.components[designator] = Component(
            uid=placement.id,
            designator=designator,
            value=_clean(attributes.get(ATTR_VALUE))
            or (device.title if device is not None else ""),
            footprint=footprint_name,
            lcsc_part=_clean(attributes.get(ATTR_LCSC)),
            manufacturer=_clean(attributes.get(ATTR_MANUFACTURER)),
            mpn=_clean(attributes.get(ATTR_MPN)),
            datasheet=_clean(attributes.get(ATTR_DATASHEET)),
            props=props,
            pins=pins_by_component.get(placement.id, []),
        )

    # Reverse-build the net list from component pins — identical to the
    # .enet path, so L1 rules see the same structure either way.
    for component in model.components.values():
        for pin in component.pins:
            if pin.net is None:
                continue
            net = model.nets.setdefault(pin.net, Net(name=pin.net))
            net.pins.append((component.designator, pin.number))

    model.raw["project"] = dict(source.project_meta)
    return model


def _pin_names_of(
    context: PcbContext,
    devices: dict[str, DeviceMeta],
    symbols: dict[str, dict[str, str]],
) -> dict[str, dict[str, str]]:
    """Placement id -> ``pin number -> Pin Name``, joined through the library.

    The join is ``placement -> DEVICE -> DEVICE["Symbol"] -> SYMBOL`` because
    the PCB document itself names no symbol (measured: placement attrs are
    ``Channel ID`` / ``Group ID`` / ``Unique ID`` / ``Value`` only). A placement
    whose device, whose ``Symbol`` attribute or whose symbol document is missing
    contributes **no** names — the pins keep ``name=""`` and every consumer
    already treats that as "not measured" rather than as "no name".

    Only *named* pins are listed. A symbol pin the library left unnamed is not
    an entry, so a lookup can never mistake the absence of an entry for a name
    that was read and found empty.
    """
    names: dict[str, dict[str, str]] = {}
    for placement in context.placements:
        device_uuid = context.device_ids.get(placement.id)
        device = devices.get(device_uuid) if device_uuid else None
        if device is None:
            continue
        symbol_uuid = _clean(device.attributes.get(ATTR_SYMBOL))
        if not symbol_uuid:
            continue
        table = symbols.get(symbol_uuid)
        if table:
            names[placement.id] = table
    return names


def _group_pins(
    context: PcbContext, names_by_component: dict[str, dict[str, str]] | None = None
) -> dict[str, list[Pin]]:
    """Group pins by component id, from footprint pads then ``PAD_NET``.

    Pads come first because they are the physical pins; ``PAD_NET`` records
    that name a pin no pad instantiated still describe real connectivity, so
    they are appended rather than dropped. ``names_by_component`` supplies the
    ``Pin Name`` the SYMBOL document declares (131a); a pin the library leaves
    unnamed keeps ``name=""``. Unconnected pins get ``net=None``.
    """
    pins: dict[str, list[Pin]] = {}
    seen: dict[str, set[str]] = {}
    names = names_by_component or {}

    def add(component_id: str, number: str, net: str | None) -> None:
        if not number:
            return
        bucket = pins.setdefault(component_id, [])
        known = seen.setdefault(component_id, set())
        if number in known:
            # Second sighting: only fill in a net the pad did not carry.
            if net is not None:
                for existing in bucket:
                    if existing.number == number and existing.net is None:
                        existing.net = net
            return
        known.add(number)
        bucket.append(
            Pin(
                number=number,
                name=names.get(component_id, {}).get(number, ""),
                net=net,
            )
        )

    for pad in context.pads:
        if pad.component_id:
            add(pad.component_id, pad.pin_number or "", pad.net)
    for (component_id, number), net in context.pad_nets_by_pin.items():
        add(component_id, number, net)

    for bucket in pins.values():
        bucket.sort(key=lambda pin: _pin_sort_key(pin.number))
    return pins
