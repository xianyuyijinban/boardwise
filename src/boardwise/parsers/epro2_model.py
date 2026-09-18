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

- ``Pin.name`` — pin *names* live in SYMBOL documents, which are dropped at
  parse time to keep memory proportional to useful data. Only pin *numbers*
  exist here. ``.enet``-sourced models do carry names.
- ``Component.role`` / ``Component.block`` — stage-2 intent metadata, still
  unpopulated everywhere.

The 4/47 components without a footprint name are the same 4 that carry no
``ATTR key="Footprint"``: they have no pad geometry in the backup either, so
they contribute no pins.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..core.model import Component, DesignModel, Net, Pin
from .epru import DEVICE_DOC_TYPE, FOOTPRINT_DOC_TYPE, Epro2Source, PcbContext

__all__ = ["DeviceMeta", "device_metas", "footprint_titles", "build_design_model"]


#: DEVICE attribute keys mapped onto the first-class Component fields. The
#: same key names are used by the ``.enet`` export, so a rule cannot tell the
#: two inputs apart.
ATTR_VALUE = "Value"
ATTR_LCSC = "Supplier Part"
ATTR_MANUFACTURER = "Manufacturer"
ATTR_MPN = "Manufacturer Part"
ATTR_DATASHEET = "Datasheet"

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
    """Return DEVICE document uuid -> its library metadata."""
    metas: dict[str, DeviceMeta] = {}
    for document in source.documents_of_type(DEVICE_DOC_TYPE):
        for record in document.records:
            if record.type != "META" or record.body is None or document.uuid is None:
                continue
            metas[document.uuid] = DeviceMeta(
                uuid=document.uuid,
                title=str(record.body.get("title") or ""),
                attributes=dict(record.body.get("attributes") or {}),
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


def _pin_sort_key(number: str) -> tuple[int, int | float, str]:
    """Sort pin numbers naturally: ``"2"`` before ``"10"``, letters last."""
    try:
        return (0, int(number), "")
    except ValueError:
        return (1, float("inf"), number)


def build_design_model(source: Epro2Source) -> DesignModel:
    """Build the netlist view of an already-decoded :class:`Epro2Source`.

    Uses the cached :class:`PcbContext`, so building geometry and the model
    from one ``.epro2`` walks the PCB document exactly once. Components are
    keyed by designator — the same key :class:`BoardGeometry` exposes through
    ``board.component(designator)`` — so the two views cross-reference.

    Returns an empty model (not an error) when the backup has no PCB
    document, so batch runs survive a backup that was saved before layout.
    """
    model = DesignModel()
    context = source.pcb_context()
    if context is None:
        model.raw["project"] = dict(source.project_meta)
        return model

    devices = device_metas(source)
    footprints = footprint_titles(source)
    pins_by_component = _group_pins(context)

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


def _group_pins(context: PcbContext) -> dict[str, list[Pin]]:
    """Group pins by component id, from footprint pads then ``PAD_NET``.

    Pads come first because they are the physical pins; ``PAD_NET`` records
    that name a pin no pad instantiated still describe real connectivity, so
    they are appended rather than dropped. Pin names stay empty (see module
    docstring); unconnected pins get ``net=None``.
    """
    pins: dict[str, list[Pin]] = {}
    seen: dict[str, set[str]] = {}

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
        bucket.append(Pin(number=number, name="", net=net))

    for pad in context.pads:
        if pad.component_id:
            add(pad.component_id, pad.pin_number or "", pad.net)
    for (component_id, number), net in context.pad_nets_by_pin.items():
        add(component_id, number, net)

    for bucket in pins.values():
        bucket.sort(key=lambda pin: _pin_sort_key(pin.number))
    return pins
