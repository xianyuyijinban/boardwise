"""Candidate :class:`DesignModel` builders for the draw verification (006).

After ``boardwise draw`` has placed and wired a schematic, the *candidate*
model — what the editor actually understood — is compared against the golden
model. Two sources, tried in this order by the draw flow:

1. **Netlist export** (preferred). ``sch.netlist`` returns the editor's own
   netlist — connectivity ground truth computed by the editor itself. The
   parser for the EasyEDA Pro flavour is calibrated against a live sample;
   until then :func:`candidate_from_netlist` raises
   :class:`NetlistFormatError` rather than guessing, because a confidently
   wrong candidate model is worse than falling back.
2. **Geometry readback** (fallback). ``sch.geometry`` dumps the placed
   primitives raw; :func:`candidate_from_geometry` rebuilds connectivity
   with the same union-find logic the file-side parser uses. Field names of
   editor state are matched *tolerantly* (case-insensitive, underscores
   ignored) because the exact names are part of what the machine run
   measures.
"""

from __future__ import annotations

from typing import Any

# `transform_point` lives in this layer (moved out of `parsers.schematic` in
# 006c): core may not import parsers, and this module needs the transform.
from boardwise.core.geometry import transform_point as _transform_point
from boardwise.core.model import Component, DesignModel, Net, Pin


class NetlistFormatError(Exception):
    """The netlist text did not match any format this parser understands."""


class GeometryError(Exception):
    """The geometry dump was unusable (missing designators, no pins at all)."""


def _norm(key: str) -> str:
    return key.replace("_", "").lower()


def field_of(state: dict[str, Any], *names: str) -> Any:
    """Tolerant state lookup: case-insensitive, underscore-insensitive.

    Public on purpose (006c): both this layer and `engines/draw.py` read editor
    state with the same forgiving lookup, and the engines used to import it as
    a **private** name across the layer boundary. A helper two layers share is
    part of `core`'s interface, not an implementation detail.
    """
    lowered = {_norm(k): v for k, v in state.items()}
    for name in names:
        value = lowered.get(_norm(name))
        if value is not None:
            return value
    return None


def as_float(value: Any) -> float | None:
    """Best-effort float conversion; `None` when the value is not numeric.

    Public for the same reason as :func:`field_of`.
    """
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _polyline(value: Any) -> list[tuple[float, float]]:
    """Read a wire's geometry as a point list, or ``[]``.

    The editor exposes wire lines either as a flat number array (x1, y1, x2,
    y2, …) or as a list of [x, y] pairs. Anything else — a scalar, a nested
    object, an odd-length flat array — yields no geometry rather than a wrong
    one.
    """
    if not isinstance(value, list) or len(value) < 2:
        return []
    if all(isinstance(v, (int, float)) for v in value):
        if len(value) % 2 != 0:
            return []
        return [(float(value[i]), float(value[i + 1])) for i in range(0, len(value), 2)]
    points: list[tuple[float, float]] = []
    for pair in value:
        if isinstance(pair, (list, tuple)) and len(pair) == 2:
            x, y = as_float(pair[0]), as_float(pair[1])
            if x is not None and y is not None:
                points.append((x, y))
    return points if len(points) >= 2 else []


def candidate_from_netlist(text: str, netlist_type: str = "EasyEDA") -> DesignModel:
    """Build a model from the editor's netlist export.

    The EasyEDA Pro flavour (``type: "EasyEDA"``) is a JSON document,
    measured on the machine 2026-09-13 (connector 0.3.0, editor 3.2.186):
    ``{"version": "2.0.0", "components": {<gge-id>: {"props": {...},
    "pinInfoMap": {<number>: {"name", "number", "net", "props"}}}},
    "designRule": …, "differentialPair": …, "netClass": …,
    "equalLengthNetGroup": …}``. Each pin carries the net *the editor*
    resolved — ground truth for the draw diff, no connectivity re-derivation.

    Deliberate mappings, chosen to match the golden side (parsed from the
    ``.epro2`` by ``parsers/schematic.py``): value = ``props.Value``,
    footprint = ``props.Supplier Footprint`` (the *semantic* footprint — the
    human-readable ``0402``/``SOP-16`` string — not the ``Footprint`` key,
    which holds a footprint-document uuid), lcsc = ``props.Supplier Part``.
    The editor *enriches* these from the library device (a golden
    schematic attr can be empty where the netlist knows the part), so the
    draw report classifies such component-level gaps as library
    enrichment, not drawing errors — see ``engines.draw``.

    Other ``netlistType`` values (Protel2, PADS, …) are text formats without
    a captured sample; they raise :class:`NetlistFormatError` rather than
    inviting a guessed parser.
    """
    import json

    stripped = text.lstrip()
    if netlist_type != "EasyEDA" or not stripped.startswith("{"):
        raise NetlistFormatError(
            f"the {netlist_type} netlist format has no calibrated parser "
            f"(got {len(text)} chars, not the EasyEDA JSON document)"
        )
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        raise NetlistFormatError(f"netlist JSON is malformed: {exc}") from exc

    components_raw = doc.get("components")
    if not isinstance(components_raw, dict) or not components_raw:
        raise NetlistFormatError("netlist JSON has no components section")

    model = DesignModel()
    for entry in components_raw.values():
        if not isinstance(entry, dict):
            continue
        props = entry.get("props") or {}
        designator = str(props.get("Designator") or "").strip()
        if not designator or designator.endswith("?"):
            continue
        component = Component(
            uid=str(entry.get("Unique ID") or props.get("Unique ID") or ""),
            designator=designator,
            value=str(props.get("Value") or "").strip(),
            # Semantic footprint first (what the golden side reports after the
            # F1 DEVICE-META join); the raw `Footprint` uuid is a last resort
            # so a netlist captured before the semantic key existed still
            # yields *something* rather than a silent empty.
            footprint=str(
                props.get("Supplier Footprint")
                or props.get("Footprint")
                or ""
            ).strip(),
            lcsc_part=str(props.get("Supplier Part") or "").strip(),
            manufacturer=str(props.get("Manufacturer") or "").strip(),
            mpn=str(props.get("Manufacturer Part") or "").strip(),
            datasheet=str(props.get("Datasheet") or "").strip(),
        )
        device_name = str(props.get("DeviceName") or "").strip()
        if device_name:
            component.props["device_name"] = device_name
        for number, pin in sorted(
            (entry.get("pinInfoMap") or {}).items(), key=lambda kv: len(kv[0]),
        ):
            # An empty net string is the editor's "unconnected" (including
            # schematic NO_CONNECT marks): model it as ``None`` exactly like
            # the golden-side parser does, or every NC pin reads as a diff.
            net = str(pin.get("net") or "").strip() or None
            component.pins.append(
                Pin(number=number, name=str(pin.get("name") or ""), net=net)
            )
            if net:
                net_obj = model.nets.setdefault(net, Net(name=net))
                if (designator, number) not in net_obj.pins:
                    net_obj.pins.append((designator, number))
        model.components[designator] = component

    if not model.components:
        raise NetlistFormatError("netlist JSON yielded no usable components")

    # The trailing sections are the same top-level blocks the file-side
    # model keeps in ``raw`` (designRule / differentialPair / netClass /
    # equalLengthNetGroup) — future rules consume them from either side.
    for key in ("designRule", "differentialPair", "netClass", "equalLengthNetGroup"):
        if key in doc:
            model.raw[key] = doc[key]
    return model


class _UnionFind:
    """The same union-find the file-side parser uses."""

    def __init__(self) -> None:
        self.parent: dict[Any, Any] = {}

    def find(self, node: Any) -> Any:
        self.parent.setdefault(node, node)
        while self.parent[node] != node:
            self.parent[node] = self.parent[self.parent[node]]
            node = self.parent[node]
        return node

    def union(self, a: Any, b: Any) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra

    def clusters(self) -> dict[Any, list[Any]]:
        out: dict[Any, list[Any]] = {}
        for node in self.parent:
            out.setdefault(self.find(node), []).append(node)
        return out


def candidate_from_geometry(
    geo: dict[str, Any],
    *,
    symbol_defs: dict[str, dict[str, tuple[float, float]]] | None = None,
    part_positions: dict[tuple[float, float], str] | None = None,
) -> DesignModel:
    """Rebuild connectivity from a ``sch.geometry`` dump, in **canvas** space.

    Pins come from the pin list when the editor exposes them; the measured
    reality on schematic pages is that ``sch_PrimitivePin.getAll()`` is
    EMPTY, so when ``symbol_defs`` and ``part_positions`` are supplied the
    pin tips are computed as *placed position + library symbol offset*:
    parts are matched to designators by exact position (the editor keeps the
    placed origin verbatim), and the offsets come from the golden file's own
    symbol definitions via the ``Symbol`` uuid each placed component reports.
    Wires contribute polyline endpoints to the connectivity graph; netflag
    primitives force net names at their points -- the editor carries their net
    in the ``Net`` state field even when the file-side attribute was empty.

    Everything here is the editor's own space, so there is nothing to convert:
    the configurator's `editor -> file` negations are gone (task 010c, M1 —
    the file stores y opposite to the canvas, the parser negates once at its
    boundary, and this builder's model is therefore canvas space). The
    ``part_positions_canvas`` flag went with them: it existed only because
    ``collect_part_placements`` used to hand back file space while the draw
    flow handed back canvas, and both are canvas now.
    """
    components_raw = geo.get("components") or []
    wires_raw = geo.get("wires") or []
    pins_raw = geo.get("pins") or []

    model = DesignModel()
    if not components_raw and not pins_raw:
        raise GeometryError("the geometry dump has neither components nor pins")

    # --- parts, at the editor's own coordinates
    placed: list[tuple[str, str, float, float, float, bool]] = []
    for entry in components_raw:
        state = entry.get("state") or {}
        comp_type = str(state.get("ComponentType") or "")
        x = as_float(field_of(state, "X"))
        y = as_float(field_of(state, "Y"))
        if x is None or y is None:
            continue
        file_point = (round(x, 2), round(y, 2))
        designator = (part_positions or {}).get(file_point, "") if comp_type == "part" else ""
        if not designator:
            continue
        component = Component(
            uid=str(entry.get("primitiveId") or ""),
            designator=designator,
            value=str(field_of(state, "Value") or ""),
            footprint=str(field_of(state, "Footprint") or ""),
            lcsc_part=str(field_of(state, "SupplierId", "Supplier") or ""),
        )
        model.components[designator] = component
        placed.append(
            (
                designator,
                str(field_of(state, "Symbol") or ""),
                x,
                y,
                float(field_of(state, "Rotation") or 0.0),
                state.get("Mirror") is True,
            )
        )

    # --- pins: editor primitives when present, symbol offsets otherwise
    pin_points: dict[tuple[str, str], tuple[float, float]] = {}
    for entry in pins_raw:
        state = entry.get("state") or {}
        number = str(field_of(state, "PinNumber", "Number") or "").strip()
        x = as_float(field_of(state, "X"))
        y = as_float(field_of(state, "Y"))
        owner = str(field_of(state, "Designator") or "").strip()
        if not number or x is None or y is None or owner not in model.components:
            continue
        if number not in {p.number for p in model.components[owner].pins}:
            model.components[owner].pins.append(Pin(number=number, name=""))
        pin_points[(owner, number)] = (x, y)

    if not pin_points and symbol_defs:
        # `_transform_point` comes from `core.geometry` (006c): this module used
        # to reach into `parsers.schematic` for it, which inverted the layering.
        for designator, symbol_uuid, x, y, rotation, mirror in placed:
            offsets = symbol_defs.get(symbol_uuid.strip()) or symbol_defs.get(designator)
            if not offsets or designator not in model.components:
                continue
            for number, (dx, dy) in offsets.items():
                px, py = _transform_point(
                    dx, dy, rotation=rotation, mirror=mirror, ox=x, oy=y
                )
                component = model.components[designator]
                if number not in {p.number for p in component.pins}:
                    component.pins.append(Pin(number=number, name=""))
                pin_points[(designator, number)] = (px, py)

    # --- connectivity: wire polylines + coincident pins
    uf = _UnionFind()
    point_index: dict[tuple[float, float], list[Any]] = {}
    PRECISION = 2

    def point_node(x: float, y: float) -> tuple[float, float]:
        return (round(x, PRECISION), round(y, PRECISION))

    wire_names: dict[Any, str] = {}
    for entry in wires_raw:
        state = entry.get("state") or {}
        net = str(field_of(state, "Net") or "").strip()
        polyline: list[tuple[float, float]] = []
        for key, value in state.items():
            points = _polyline(value)
            if len(points) > len(polyline):
                polyline = points
        if not polyline:
            continue
        nodes = []
        for x, y in polyline:
            pt = point_node(x, y)  # the editor's own canvas coordinates
            node = ("w", pt)
            uf.find(node)
            point_index.setdefault(pt, []).append(node)
            nodes.append(node)
        for a, b in zip(nodes, nodes[1:]):
            uf.union(a, b)  # consecutive polyline points are connected
        if net:
            for node in nodes:
                wire_names.setdefault(node, net)

    for nodes in point_index.values():
        for other in nodes[1:]:
            uf.union(nodes[0], other)

    # --- pins join whatever their point touches
    for (des, number), (x, y) in pin_points.items():
        node = ("p", des, number)
        uf.find(node)
        for other in point_index.get(point_node(x, y), []):
            uf.union(node, other)

    # --- net flags force names at their points (per node, so later unions
    # cannot orphan a name onto a stale root)
    forced: dict[Any, str] = {}
    for entry in components_raw:
        state = entry.get("state") or {}
        if str(state.get("ComponentType") or "") != "netflag":
            continue
        name = str(field_of(state, "Net", "NetName") or "").strip()
        x = as_float(field_of(state, "X"))
        y = as_float(field_of(state, "Y"))
        if not name or x is None or y is None:
            continue
        for other in point_index.get(point_node(x, y), []):
            forced.setdefault(other, name)
    for entry in geo.get("netlabels") or []:
        state = entry.get("state") or {}
        name = str(field_of(state, "Net", "NetName") or "").strip()
        x = as_float(field_of(state, "X"))
        y = as_float(field_of(state, "Y"))
        if not name or x is None or y is None:
            continue
        for other in point_index.get(point_node(x, y), []):
            forced.setdefault(other, name)

    # --- name clusters, resolving per-node names through the final roots
    explicit: dict[Any, str] = {}
    clusters = uf.clusters()
    for root, nodes in clusters.items():
        name = next(
            (v for v in (forced.get(n) or wire_names.get(n) or "" for n in nodes) if v),
            "",
        )
        if name:
            explicit[root] = name
    counter = 0
    for root, nodes in clusters.items():
        if root in explicit:
            continue
        pin_count = sum(1 for node in nodes if node[0] == "p")
        # A cluster of one pin with no name is a dangling stub, not a net:
        # naming it would turn the editor's "unconnected" into a false diff.
        # (Measured: the golden board has stub wires on U1.10-14.)
        if pin_count >= 2 or any(node[0] == "w" for node in nodes):
            counter += 1
            explicit[root] = f"NET{counter}"

    nets: dict[str, Net] = {}
    for (des, number), _pt in pin_points.items():
        node = ("p", des, number)
        name = explicit.get(uf.find(node), "")
        component = model.components[des]
        for pin in component.pins:
            if pin.number == number:
                pin.net = name or None
        if name:
            net = nets.setdefault(name, Net(name=name))
            if (des, number) not in net.pins:
                net.pins.append((des, number))
    model.nets = nets
    return model
