"""Golden-layout replay: the draw flow's default plan source (task 006b).

The 006 verdict on the solver's output was "completely unusable" — wires
crossing parts, no zoning, off the frame. The answer is not a better solver
but an architectural one, decided with 岳翔宇: **layout is data**. The golden
``.epro2`` already contains a human's placement — every COMPONENT's
x/y/rotation/mirror, every wire, every net label anchor — and copying it
inherits zoning, orientation and spacing for free. The generic solver in
:mod:`boardwise.engines.layout` stays as the fallback for boards without
reference geometry.

Coordinate contract (the sign trap this project has hit twice):

* the golden file's page space is **y up**, the editor canvas is **y down**;
  the single conversion is ``canvas = (x, -y)`` and it happens exactly here;
* a *placement* keeps its rotation/mirror verbatim — the editor applies the
  same convention the file stores, so a replayed part sits exactly where it
  did, and its pins land on the replayed wires by construction;
* the page **offset** is snapped to :data:`OFFSET_GRID` so every pin tip keeps
  the 5-unit lattice the wire endpoints share.

Sheet geometry is *measured*, never nominal: the frame comes from the target
page's own sheet primitive bbox (``sch.geometry`` + ``sch_Primitive
.getPrimitivesBBox``), the title block is carved from that bbox by the
A-series-landscape ratio the reference implementation also uses (0.6 x 0.24,
bottom-right — cross-checked against a rendered page, see ``docs/draw.md``),
and when no measurement is available the replay refuses instead of guessing.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from boardwise.core.geometry import transform_point as _transform_point
from boardwise.core.model import DesignModel
from boardwise.engines import layout
from boardwise.engines.generate import (
    DEFAULT_NAMING_STRATEGY,
    DEFAULT_PITCH,
    NAMING_STRATEGIES,
    ActionPlan,
    NetNameStep,
    PlacementStep,
    WireStep,
    canvas_pin_offsets,
    normalise_strategy,
    strip_dangling_nets,
)
from boardwise.engines.layout import Placement, Rect, RoutedNet, Violation
from boardwise.parsers.schematic import (
    PageLayout,

)

#: The page offset is snapped to this lattice so pins stay on the wire grid.
OFFSET_GRID = 5.0

#: Tolerance added to a part's *measured drawn extent* when bounding it.
#: Deliberately **zero**: the human's own decoupling capacitors sit exactly
#: one pin-lead away from the chip they decouple, so any generous pad reports
#: the human's own board as overlapping (measured: a 20-unit pad yields 19
#: false ``BOX_OVERLAP`` rows, and even a 3-unit pad clips the neighbouring
#: label boxes). The validator's crossing test is interior-only, so a wire
#: that merely *ends* on a body edge stays legal.
BODY_PAD = 0.0

#: A-series landscape title-block ratio (reference implementation's table:
#: ``sheet-templates.json`` -> templates[a-series-landscape].titleBlock).
TITLE_BLOCK_WIDTH_FRAC = 0.6
TITLE_BLOCK_HEIGHT_FRAC = 0.24


@dataclass
class SheetFrame:
    """The target page's drawing area, in canvas units.

    ``bbox`` is the sheet primitive's measured bbox; ``drawable`` is that
    deflated by the frame margin (the inner drawing area); ``title_block`` is
    the bottom-right keep-out carved by ratio.
    """

    bbox: Rect
    drawable: Rect
    title_block: Rect
    provenance: str = "measured"
    notes: list[str] = field(default_factory=list)

    def render(self) -> str:
        return (
            f"sheet {self.bbox.x0:.0f},{self.bbox.y0:.0f}-{self.bbox.x1:.0f},{self.bbox.y1:.0f}"
            f" | drawable {self.drawable.x0:.0f},{self.drawable.y0:.0f}"
            f"-{self.drawable.x1:.0f},{self.drawable.y1:.0f}"
            f" | title block {self.title_block.x0:.0f},{self.title_block.y0:.0f}"
            f"-{self.title_block.x1:.0f},{self.title_block.y1:.0f}"
            f" ({self.provenance})"
        )


def _ratio_title_block(bbox: Rect) -> Rect:
    """Bottom-right sub-rect of ``bbox`` by the A-series landscape ratio."""
    width = (bbox.x1 - bbox.x0) * TITLE_BLOCK_WIDTH_FRAC
    height = (bbox.y1 - bbox.y0) * TITLE_BLOCK_HEIGHT_FRAC
    return Rect(bbox.x1 - width, bbox.y1 - height, bbox.x1, bbox.y1)


def sheet_frame_from_bbox(
    bbox: Rect, *, frame: float = layout.FRAME, provenance: str = "measured"
) -> SheetFrame:
    """Build a :class:`SheetFrame` from a measured (or declared) sheet bbox."""
    drawable = Rect(bbox.x0 + frame, bbox.y0 + frame, bbox.x1 - frame, bbox.y1 - frame)
    return SheetFrame(
        bbox=bbox,
        drawable=drawable,
        title_block=_ratio_title_block(bbox),
        provenance=provenance,
    )


def sheet_frame_from_geometry(
    geo: dict, *, declared: dict[str, str] | None = None, origin: tuple[float, float] = (0.0, 0.0)
) -> SheetFrame | None:
    """Measure the target page's frame from a ``sch.geometry`` dump.

    Priority: the sheet primitive's **measured** bbox (``bboxes`` section,
    from ``getPrimitivesBBox``). When the host does not expose bboxes, the
    golden page's **declared** ``Width``/``Height`` may be used instead — both
    are data, neither is a nominal guess — and the provenance says which.
    Returns ``None`` when neither is available: the caller must then refuse
    rather than invent an A4.
    """
    want = {
        str(entry.get("primitiveId"))
        for entry in geo.get("components") or []
        if str((entry.get("state") or {}).get("ComponentType") or "") == "sheet"
    }
    measured = None
    for prim_id, box in (geo.get("bboxes") or {}).items():
        if prim_id in want and box:
            measured = Rect(
                float(box["minX"]), float(box["minY"]), float(box["maxX"]), float(box["maxY"])
            )
            break
    if measured is not None:
        frame = sheet_frame_from_bbox(measured, provenance="measured")
        if not want:
            frame.notes.append("no sheet primitive in the dump; bbox taken from the bbox map")
        return frame

    if declared:
        try:
            width = float(declared.get("Width") or "")
            height = float(declared.get("Height") or "")
        except ValueError:
            return None
        if width > 0 and height > 0:
            # The declared size is anchored at the sheet's origin; with the
            # file's y-up page space the sheet extends upward, so in canvas
            # space it spans [origin.y, origin.y + height].
            ox, oy = origin
            bbox = Rect(ox, -oy, ox + width, -oy + height)
            frame = sheet_frame_from_bbox(bbox, provenance="declared-size")
            frame.notes.append(
                "frame from the declared page size (no measurable sheet bbox on this host)"
            )
            return frame
    return None


# --------------------------------------------------------------------------
# the plan
# --------------------------------------------------------------------------


def _rotated_canvas_offsets(
    offsets: dict[str, tuple[float, float]], rotation: float, mirror: bool
) -> dict[str, tuple[float, float]]:
    """File-space pin offsets -> canvas offsets for a *rotated* placement.

    The parser's offsets are file space and unrotated; a placed instance
    rotates them (clockwise, y-up) and mirrors across the vertical axis. The
    result is converted to canvas space (y negated) so it can be added to a
    canvas placement, which is what the box and the self-check work in.
    """
    out: dict[str, tuple[float, float]] = {}
    for number, (dx, dy) in offsets.items():
        fx, fy = _transform_point(dx, dy, rotation=rotation, mirror=mirror, ox=0.0, oy=0.0)
        out[number] = (fx, -fy)
    return out


def _content_bbox(boxes: list[Rect], points: list[tuple[float, float]]) -> Rect | None:
    xs0 = [b.x0 for b in boxes] + [p[0] for p in points]
    ys0 = [b.y0 for b in boxes] + [p[1] for p in points]
    xs1 = [b.x1 for b in boxes] + [p[0] for p in points]
    ys1 = [b.y1 for b in boxes] + [p[1] for p in points]
    if not xs0:
        return None
    return Rect(min(xs0), min(ys0), max(xs1), max(ys1))


def _body_box(
    x: float,
    y: float,
    rotation: float,
    mirror: bool,
    body: tuple[float, float, float, float],
    dx: float = 0.0,
    dy: float = 0.0,
) -> Rect:
    """A symbol-local body rectangle placed at ``(x, y)`` -> canvas box."""
    xs: list[float] = []
    ys: list[float] = []
    for bx, by in ((body[0], body[1]), (body[0], body[3]), (body[2], body[1]), (body[2], body[3])):
        fx, fy = _transform_point(bx, by, rotation=rotation, mirror=mirror, ox=x, oy=y)
        xs.append(fx + dx)
        ys.append(-fy + dy)
    return Rect(min(xs), min(ys), max(xs), max(ys))


def part_box(
    part,
    offsets: dict[str, tuple[float, float]],
    bodies: dict[str, tuple[float, float, float, float]] | None,
    *,
    pad: float = BODY_PAD,
) -> Rect | None:
    """The part's keep-out box: its **measured drawn extent**, canvas space.

    Priority: the symbol's drawn geometry (:func:`collect_symbol_bodies` —
    RECT/POLY/CIRCLE, the thing a human sees), fallback the pin extents.
    Both are rotated by the instance and converted to canvas space through
    :func:`_transform_point`, so a rotated part is bounded where it actually
    sits.
    """
    body = (bodies or {}).get(part.symbol_uuid)
    if body is not None:
        corners = [(body[0], body[1]), (body[0], body[3]), (body[2], body[1]), (body[2], body[3])]
    else:
        corners = list(offsets.values())
    if not corners:
        return None
    xs: list[float] = []
    ys: list[float] = []
    for dx, dy in corners:
        fx, fy = _transform_point(
            dx, dy, rotation=part.rotation, mirror=part.mirror, ox=part.x, oy=part.y
        )
        xs.append(fx)
        ys.append(-fy)
    return Rect(min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad)


def _snap(value: float) -> float:
    return round(value / OFFSET_GRID) * OFFSET_GRID


def place_offset(content: Rect, frame: SheetFrame) -> tuple[tuple[float, float], list[str]]:
    """The page translation: centred in the drawable area, off the title block.

    Deterministic. Centring is the goal; the title block and the frame are
    hard constraints, and the result is snapped to :data:`OFFSET_GRID` so the
    pin lattice survives. Returns ``(dx, dy)`` and notes explaining any
    deviation from plain centring.
    """
    notes: list[str] = []
    draw = frame.drawable
    dx = _snap((draw.x0 + draw.x1) / 2 - (content.x0 + content.x1) / 2)
    dy = _snap((draw.y0 + draw.y1) / 2 - (content.y0 + content.y1) / 2)

    def fits(ox: float, oy: float) -> bool:
        moved = Rect(content.x0 + ox, content.y0 + oy, content.x1 + ox, content.y1 + oy)
        if moved.x0 < draw.x0 or moved.y0 < draw.y0 or moved.x1 > draw.x1 or moved.y1 > draw.y1:
            return False
        return not moved.intersects(frame.title_block)

    if fits(dx, dy):
        return (dx, dy), notes

    # Push out of the title block, preferring the smaller displacement, then
    # clamp back inside the frame.
    bx = frame.title_block.x0 - 20.0 - content.x1
    by = frame.title_block.y0 - 20.0 - content.y1
    candidates = []
    if fits(_snap(bx), dy):
        candidates.append((_snap(bx), dy, "shifted left of the title block"))
    if fits(dx, _snap(by)):
        candidates.append((dx, _snap(by), "shifted above the title block"))
    if candidates:
        ox, oy, why = min(candidates, key=lambda c: abs(c[0] - dx) + abs(c[1] - dy))
        notes.append(why)
        return (ox, oy), notes

    ox = min(max(dx, draw.x0 - content.x0), draw.x1 - content.x1)
    oy = min(max(dy, draw.y0 - content.y0), draw.y1 - content.y1)
    notes.append("centred offset clamped to the frame; the title block could not be cleared")
    return (_snap(ox), _snap(oy)), notes


def _shift(box: Rect, dx: float, dy: float) -> Rect:
    return Rect(box.x0 + dx, box.y0 + dy, box.x1 + dx, box.y1 + dy)


def _resolve_run_nets(
    runs: list[list[tuple[float, float]]],
    pin_net_page: dict[tuple[float, float], str],
) -> list[str]:
    """Effective net name per wire run, from the model's own connectivity.

    The file names only the labelled wires (``RX``, ``TX``, ``D±``); the rail
    wires are unnamed there because the human named those with flags. The
    *effective* net of a run therefore has to come from connectivity, and the
    editor's own rule set says two things the file's serialisation hides:

    * a **pin tip on a wire** connects (even mid-segment), and
    * a **wire endpoint on another wire** connects — the editor draws a
      junction dot there.

    So runs, pin tips and endpoint-on-segment touches go into one union-find,
    and a run takes the net of any pin in its cluster. Anything left without a
    pin keeps its own name (or no name). Without this, a rail stub whose end
    lands on the GND bus looks like a *foreign* net and the self-check reports
    the human's own board as a short — measured, 6 such false rows.
    """
    parent: dict[tuple[float, float], tuple[float, float]] = {}

    def key(point: tuple[float, float]) -> tuple[float, float]:
        return (round(point[0], 2), round(point[1], 2))

    def find(node: tuple[float, float]) -> tuple[float, float]:
        parent.setdefault(node, node)
        root = node
        while parent[root] != root:
            root = parent[root]
        while parent[node] != root:
            parent[node], node = root, parent[node]
        return root

    def union(a: tuple[float, float], b: tuple[float, float]) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    segments: list[tuple[tuple[float, float], tuple[float, float]]] = []
    for run in runs:
        for point in run:
            find(key(point))
        for a, b in zip(run, run[1:]):
            union(key(a), key(b))
            segments.append((key(a), key(b)))

    for point in pin_net_page:
        find(key(point))
    for point in pin_net_page:
        pk = key(point)
        for a, b in segments:
            if layout._point_on_segment(pk, layout.Segment(a[0], a[1], b[0], b[1], "")):
                union(pk, a)
    for run in runs:
        for endpoint in (run[0], run[-1]) if run else ():
            ep = key(endpoint)
            for a, b in segments:
                if layout._point_on_segment(ep, layout.Segment(a[0], a[1], b[0], b[1], "")):
                    union(ep, a)

    net_of_root: dict[tuple[float, float], str] = {}
    for point, net in pin_net_page.items():
        net_of_root.setdefault(find(key(point)), net)

    out: list[str] = []
    for run in runs:
        if not run:
            out.append("")
            continue
        out.append(net_of_root.get(find(key(run[0])), ""))
    return out


def build_replay_plan(
    model: DesignModel,
    page: PageLayout,
    frame: SheetFrame,
    offsets_file: dict[str, dict[str, tuple[float, float]]],
    bodies: dict[str, tuple[float, float, float, float]] | None = None,
    strategy: str | None = None,
) -> ActionPlan:
    """Replay the golden page's layout as an :class:`ActionPlan`.

    Pure: no bridge, no editor, no I/O. ``offsets_file`` are the parser's
    *file-space* pin offsets (``build_pin_offsets``); they are rotated per
    instance and converted to canvas space here, so the plan's pin positions
    are the true tips of the replayed placements — which is what the
    self-check validates against the replayed wires. ``bodies`` are the
    measured drawn extents (:func:`collect_symbol_bodies`) the lint bounds
    parts with. ``strategy`` is the signal-naming policy
    (:data:`~boardwise.engines.generate.NAMING_STRATEGIES`); a golden net
    *label* is replayed as whatever that policy says a signal name is — text
    by default, a native label under ``label``, nothing under ``wire``/``none``
    (where the wire itself carries the name).
    """
    plan = ActionPlan()
    plan.naming_strategy = normalise_strategy(strategy)
    placed = {p.designator: p for p in page.parts}

    # --- part boxes at their golden positions (canvas space)
    golden_boxes: dict[str, Rect] = {}
    per_part_offsets: dict[str, dict[str, tuple[float, float]]] = {}
    for part in page.parts:
        rotated = _rotated_canvas_offsets(
            offsets_file.get(part.designator, {}), part.rotation, part.mirror
        )
        per_part_offsets[part.designator] = rotated
        box = part_box(part, offsets_file.get(part.designator, {}), bodies)
        if box is None:
            plan.notes.append(f"{part.designator}: no pins and no drawn symbol; cannot be bounded")
        else:
            golden_boxes[part.designator] = box

    wire_points = [(x, -y) for wire in page.wires for x, y in wire.points]
    anchors = (
        [(label.x, -label.y) for label in page.labels]
        + [(flag.x, -flag.y) for flag in page.flags]
    )
    content = _content_bbox(list(golden_boxes.values()), wire_points + anchors)
    if content is None:
        plan.notes.append("the golden page has no geometry to replay")
        return plan

    (dx, dy), offset_notes = place_offset(content, frame)
    plan.notes.extend(offset_notes)
    plan.notes.append(f"page offset ({dx:.0f}, {dy:.0f}) from the golden coordinates")

    def to_page(x: float, y: float) -> tuple[float, float]:
        return (x + dx, -y + dy)

    # --- placements: rotation and mirror verbatim (see the module docstring)
    for part in page.parts:
        component = model.components.get(part.designator)
        plan.placements.append(
            PlacementStep(
                designator=part.designator,
                x=part.x + dx,
                y=-part.y + dy,
                rotation=part.rotation,
                mirror=part.mirror,
                lcsc=component.lcsc_part if component else "",
                keyword=(
                    (component.value or component.props.get("device_name", ""))
                    if component
                    else ""
                ),
                value=component.value if component else "",
                footprint=component.footprint if component else "",
                device_uuid=(
                    component.props.get("place_device_uuid", "") if component else ""
                ),
                library_uuid=(
                    component.props.get("place_library_uuid", "") if component else ""
                ),
            )
        )
    plan.geometry = [
        Placement(
            designator=designator,
            x=placed[designator].x + dx,
            y=-placed[designator].y + dy,
            bbox=_shift(box, dx, dy),
        )
        for designator, box in sorted(golden_boxes.items())
    ]

    # --- pin tips: replayed origin + rotated symbol offset, and the net each
    # pin carries in the model (the connectivity authority)
    pin_positions: dict[tuple[str, str], tuple[float, float]] = {}
    pin_net_page: dict[tuple[float, float], str] = {}
    for part in page.parts:
        component = model.components.get(part.designator)
        for number, (ox, oy) in per_part_offsets[part.designator].items():
            page_point = (part.x + dx + ox, -part.y + dy + oy)
            pin_positions[(part.designator, number)] = page_point
        if component is None:
            continue
        for pin in component.pins:
            offset = per_part_offsets[part.designator].get(pin.number)
            if offset is None or not pin.net:
                continue
            pin_net_page[
                (round(part.x + dx + offset[0], 2), round(-part.y + dy + offset[1], 2))
            ] = pin.net
    plan.pin_positions = pin_positions

    # --- wires and their effective nets, one route per net
    #
    # One route per *net* (not per run): the terminality check has to see all
    # of a net's segments to recognise a junction between two of its runs,
    # and the lint looks its wires up by net name.
    runs = [
        [to_page(x, y) for x, y in wire.points]
        for wire in page.wires
        if len(wire.points) >= 2
    ]
    effective = _resolve_run_nets(runs, pin_net_page)
    grouped: dict[str, list[list[tuple[float, float]]]] = {}
    unnamed = 0
    for wire, run, net in zip(page.wires, runs, effective):
        # Faithful on the wire itself: the connector passes `net` through only
        # when the source had one, so rails stay unnamed exactly as the human
        # left them and the editor derives them from the flags.
        plan.wires.append(WireStep(net=wire.net, points=run))
        if not wire.net:
            unnamed += 1
        grouped.setdefault(net or wire.net or f"__net_{wire.group}", []).append(run)
    # T-junctions are split *after* every run is known, so that a run's
    # endpoint landing on another run's interior can still become a vertex.
    plan.wires, _split_count = split_at_junctions(plan.wires)

    routes = [
        RoutedNet(net=net, polylines=polylines, attach=None, kind="wire")
        for net, polylines in sorted(grouped.items())
    ]
    if unnamed:
        plan.notes.append(
            f"{unnamed} wire run(s) carry no net name in the source "
            "(the editor derives them from the flags)"
        )

    # --- names: power/ground flags where the human put them; signal names
    # per the strategy (岳翔宇's rule: signal nets are named with a visible
    # label, never a port — on this host the visible form is text)
    annotation_boxes: list[Rect] = []
    for flag in page.flags:
        glyph = None
        body = (bodies or {}).get(flag.symbol_uuid)
        if body is not None:
            glyph = _body_box(flag.x, flag.y, flag.rotation, flag.mirror, body, dx, dy)
        plan.net_names.append(
            NetNameStep(
                net=flag.net,
                kind=flag.kind,
                x=flag.x + dx,
                y=-flag.y + dy,
                rotation=flag.rotation,
                mirror=flag.mirror,
            )
        )
        annotation_boxes.append(
            layout.annotation_box(flag.x + dx, -flag.y + dy, flag.net, glyph)
        )
    for label in page.labels:
        if plan.naming_strategy == "text":
            step = NetNameStep(
                net=label.net,
                kind="text",
                x=label.x + dx,
                y=-label.y + dy,
                rotation=label.rotation,
                decorative=True,
            )
        elif plan.naming_strategy == "label":
            step = NetNameStep(
                net=label.net,
                kind="label",
                x=label.x + dx,
                y=-label.y + dy,
                rotation=label.rotation,
            )
        else:
            # `wire` / `none`: the name travels on the wire (or not at all) —
            # nothing is placed, so nothing needs linting.
            continue
        plan.net_names.append(step)
        annotation_boxes.append(
            layout.annotation_box(label.x + dx, -label.y + dy, label.net)
        )

    # --- NC pins: golden pins with no net, listed so the report can tell
    # "left open on purpose" from "forgotten"
    for designator in sorted(model.components):
        if designator not in placed:
            continue
        for pin in model.components[designator].pins:
            if pin.net is None:
                plan.nc_pins.append((designator, pin.number))

    # --- the five hard constraints, plus the annotation lint
    #
    # `annotation_points` marks wire ends the human terminated by naming them.
    # It is a *geometric* fact about the golden page, so it must not depend on
    # the naming strategy: under `wire`/`none` nothing is placed, yet the wire
    # still legitimately ends where the human's label/flag sits. Feeding only
    # `plan.net_names` made those ends look unterminated in exactly the two
    # strategies that draw no name — a false positive about *our* ruler, not a
    # defect in the human's geometry.
    annotation_points = sorted(
        {(round(step.x, 2), round(step.y, 2)) for step in plan.net_names}
        | {(round(label.x + dx, 2), round(-label.y + dy, 2)) for label in page.labels}
        | {(round(flag.x + dx, 2), round(-flag.y + dy, 2)) for flag in page.flags}
    )
    members_by_net = {
        name: {des for des, _pin in net.pins} for name, net in model.nets.items()
    }
    plan.violations = layout.validate_full(
        model,
        plan.geometry,
        routes,
        pin_positions,
        frame=frame.drawable,
        title_block=frame.title_block,
        annotation_points=annotation_points,
    )
    plan.violations.extend(
        layout.lint_annotations(
            plan.geometry,
            routes,
            plan.net_names,
            frame.title_block,
            boxes=annotation_boxes,
            members_by_net=members_by_net,
        )
    )
    return plan


def _on_segment(point, a, b, tol: float = 0.01) -> bool:
    """Is ``point`` on the segment a-b, strictly between the two ends?"""
    (px, py), (ax, ay), (bx, by) = point, a, b
    if abs((bx - ax) * (py - ay) - (by - ay) * (px - ax)) > tol:
        return False
    if not (min(ax, bx) - tol <= px <= max(ax, bx) + tol):
        return False
    if not (min(ay, by) - tol <= py <= max(ay, by) + tol):
        return False
    return (abs(px - ax) > tol or abs(py - ay) > tol) and (
        abs(px - bx) > tol or abs(py - by) > tol
    )


def _key(point: tuple[float, float]) -> tuple[float, float]:
    return (round(point[0], 3), round(point[1], 3))


def split_at_junctions(wires: list[WireStep]) -> tuple[list[WireStep], int]:
    """Every point where two runs touch becomes an endpoint of both.

    Measured 2026-09-15, first on the golden board's U1.16/VCC and then with
    five probes: `sch_PrimitiveWire.create` **merges polylines that share an
    endpoint into one primitive** and repeats the junction point. When a run's
    endpoint lands on another run's *interior*, the merged polyline can end up
    with a pin tip in its middle — and the netlist then does not connect that
    pin. Handing the same geometry over as segments that all *end* at the
    junction is what the editor itself does for a junction, and the pin lands
    on an endpoint: verified on the live page (U1.16 joined VCC).

    Returns the split list and how many runs were split.
    """
    if len(wires) < 2:
        return list(wires), 0

    points: list[list[tuple[float, float]]] = [list(w.points) for w in wires]

    # An endpoint that sits inside another run's *segment* has to become a
    # vertex there first, or splitting would cut the wrong place.
    ends = {_key(p) for pts in points for p in (pts[0], pts[-1])}
    for pts in points:
        index = 1
        while index < len(pts):
            a, b = pts[index - 1], pts[index]
            inserts = [
                p for p in ends
                if _on_segment(p, a, b)
            ]
            inserts.sort(key=lambda p: (abs(p[0] - a[0]) + abs(p[1] - a[1])))
            for p in inserts:
                pts.insert(index, p)
                index += 1
            index += 1

    # A vertex that another run ends at becomes a split point.
    junction = set(ends)
    out: list[WireStep] = []
    split_count = 0
    for wire, pts in zip(wires, points):
        cuts = [
            i for i, p in enumerate(pts)
            if 0 < i < len(pts) - 1 and _key(p) in junction
        ]
        if not cuts:
            out.append(WireStep(net=wire.net, points=list(pts)))
            continue
        split_count += 1
        start = 0
        for cut in cuts:
            piece = pts[start:cut + 1]
            if len(piece) >= 2:
                out.append(WireStep(net=wire.net, points=piece))
            start = cut
        tail = pts[start:]
        if len(tail) >= 2:
            out.append(WireStep(net=wire.net, points=tail))
    return out, split_count


def replay_or_solver(
    model: DesignModel,
    page: PageLayout | None,
    frame: SheetFrame | None,
    offsets_file: dict[str, dict[str, tuple[float, float]]],
    *,
    bodies: dict[str, tuple[float, float, float, float]] | None = None,
    prefer_replay: bool = True,
    strategy: str | None = None,
) -> tuple[ActionPlan, str]:
    """Pick the plan source: golden replay when possible, solver otherwise.

    Returns ``(plan, source)`` where ``source`` is ``"golden replay"`` or
    ``"generic solver"`` — the draw report prints it, because a silently
    different layout strategy is exactly the kind of thing that makes a
    failure unreproducible. ``strategy`` is the signal-naming policy and is
    carried on the returned plan (:attr:`ActionPlan.naming_strategy`).
    """
    policy = normalise_strategy(strategy)
    if prefer_replay and page is not None and page.parts and frame is not None:
        return (
            build_replay_plan(model, page, frame, offsets_file, bodies, policy),
            "golden replay",
        )

    from boardwise.engines.generate import generate_plan

    plan = generate_plan(model, canvas_pin_offsets(offsets_file), policy)
    if page is None or not page.parts:
        plan.notes.append("no golden layout available; used the generic solver")
    elif frame is None:
        plan.notes.append("no measured sheet frame; used the generic solver")
    return plan, "generic solver"


__all__ = [
    "DEFAULT_NAMING_STRATEGY",
    "DEFAULT_PITCH",
    "NAMING_STRATEGIES",
    "OFFSET_GRID",
    "SheetFrame",
    "build_replay_plan",
    "place_offset",
    "replay_or_solver",
    "sheet_frame_from_bbox",
    "sheet_frame_from_geometry",
    "strip_dangling_nets",
]
