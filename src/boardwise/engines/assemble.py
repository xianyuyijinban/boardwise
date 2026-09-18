"""The assembly engine: block templates + a board spec -> a drawable design.

Task 008's bet is that a page can be *composed* rather than solved: place
blocks, replay each block's own geometry, and connect the blocks by net name
only (008 constitution items 1-2, and 岳翔宇's R2). This module is that
composition. It is pure — no bridge, no editor, no I/O — and it produces
exactly the four inputs the existing draw chain already consumes:

* a :class:`~boardwise.core.model.DesignModel` — the **spec netlist**, derived
  from the templates' own connectivity plus the spec's connections. This is the
  artifact task 008a work item 4 wants as the judgement source, so the draw's
  verdict is "candidate vs the specification", not "candidate vs the golden
  geometry";
* a :class:`~boardwise.parsers.schematic.PageLayout` at the assembled
  positions, which ``engines.replay`` replays verbatim (including R5's
  ``split_at_junctions``);
* the file-space symbol offsets and measured symbol bodies the replay and the
  lint need.

Three things it refuses to paper over:

* **Two blocks claiming the same designator.** A template's refs are used
  verbatim; a collision is an error, not a silent renumber — 008a's scope is
  one instance per block, and per-instance designator allocation is 008c's job.
* **An ambiguous net name.** Two blocks whose nets end up with the same page
  name without a connection joining them is exactly the mistake that would make
  two circuits quietly become one; it is reported with both sides named.

Naming anchors come from one of **two paths**, and which one applies is decided
by whether the template carries geometry (2026-09-17 ruling):

* **A template with geometry** (a ``board-extract``) replays the anchors the cut
  actually saw: its flags and labels are translated onto the page, and a port
  whose anchor is missing is an error — the block is a measurement, and a
  measurement with a hole in it is a defect in the cut, not something to paper
  over with a synthesised point.
* **A template with no geometry** (a ``datasheet-extract`` or a ``textbook``
  block) has no measured anchor at all, so the assembler **synthesises** one per
  pin endpoint: a short vertical stub and a power/ground flag on every rail
  endpoint, a net label on every signal endpoint. There is nothing to invent
  about a flag symbol — the editor resolves the glyph from ``kind`` + ``net``
  (measured: seventeen flags on the golden page, and
  ``sch.place_power`` takes no symbol uuid); what a synthesised anchor needs is
  a *position*, and the pin endpoints supply it. Both facts are pinned by
  ``tools/_probe_flag_anchor.py``.

Coordinates: templates are block-local **file** coordinates, and the assembler
translates them by ``instance.at - template.origin_file``. The file→canvas
conversion still happens in exactly one place (``engines.replay``), which is
why nothing here mentions the canvas.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from boardwise.core.blocks import (
    DESIGNATOR_STRIDE,
    BlockError,
    BlockComponent,
    BlockTemplate,
    BoardSpec,
    designator_map,
    instance_ordinals,
    repeated_templates,
    template_identity,
)
from boardwise.core.geometry import transform_point
from boardwise.core.model import Component, DesignModel, Net, Pin
from boardwise.parsers.schematic import (
    NetLabelAnchor,
    PageLayout,
    PlacedFlag,
    PlacedPart,
    WireRun,
)

Point = tuple[float, float]


class AssemblyError(BlockError):
    """The spec and its templates cannot be composed into one design."""


@dataclass
class PortPlacement:
    """One resolved interface: where it went and what net it ended up on."""

    block: str
    role: str
    net_class: str
    local_net: str
    page_net: str
    position: Point
    connected: bool


@dataclass
class ConnectionReport:
    """One page-level net and the ports the spec put on it."""

    net: str
    ports: list[tuple[str, str]]
    joined: list[str]


@dataclass
class AssembledDesign:
    """Everything the draw flow needs, all of it derived from the spec."""

    name: str
    model: DesignModel
    page: PageLayout
    offsets: dict[str, dict[str, Point]]
    symbol_defs: dict[str, dict[str, Point]]
    bodies: dict[str, tuple[float, float, float, float]]
    ports: list[PortPlacement] = field(default_factory=list)
    connections: list[ConnectionReport] = field(default_factory=list)
    report: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def bbox_file(self) -> tuple[float, float, float, float] | None:
        """The assembled content's extent in file coordinates."""
        xs: list[float] = []
        ys: list[float] = []
        for part in self.page.parts:
            xs.append(part.x)
            ys.append(part.y)
        for wire in self.page.wires:
            for x, y in wire.points:
                xs.append(x)
                ys.append(y)
        for flag in self.page.flags:
            xs.append(flag.x)
            ys.append(flag.y)
        for label in self.page.labels:
            xs.append(label.x)
            ys.append(label.y)
        if not xs:
            return None
        return (min(xs), min(ys), max(xs), max(ys))


class _Groups:
    """Minimal union-find over ``(block id, local net)`` nodes."""

    def __init__(self) -> None:
        self._parent: dict[tuple[str, str], tuple[str, str]] = {}

    def add(self, node: tuple[str, str]) -> None:
        self._parent.setdefault(node, node)

    def find(self, node: tuple[str, str]) -> tuple[str, str]:
        self.add(node)
        root = node
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[node] != root:
            self._parent[node], node = root, self._parent[node]
        return root

    def union(self, a: tuple[str, str], b: tuple[str, str]) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self._parent[rb] = ra

    def clusters(self) -> dict[tuple[str, str], list[tuple[str, str]]]:
        out: dict[tuple[str, str], list[tuple[str, str]]] = {}
        for node in sorted(self._parent):
            out.setdefault(self.find(node), []).append(node)
        return out


def _check_designators(spec: BoardSpec) -> None:
    """No **page** designator may be claimed twice.

    Checked on the derived names (`designator_map`), not on the template refs:
    two instances of one template would otherwise be reported as fifty clashes
    even though the derivation keeps them apart, while a genuine collision — two
    blocks that share a ref, or a template whose numbering range is wider than
    the stride — is still caught. The rule is "a name is claimed once", whatever
    produced it.
    """
    owner: dict[str, str] = {}
    clashes: list[str] = []
    for block in spec.blocks:
        for page_ref in designator_map(spec)[block.id].values():
            if page_ref in owner:
                clashes.append(
                    f"{page_ref}: block {owner[page_ref]!r} and block {block.id!r}"
                )
            else:
                owner[page_ref] = block.id
    if clashes:
        raise AssemblyError(
            "the same page designator is claimed twice; a repeated template is "
            f"offset by {DESIGNATOR_STRIDE} per instance ordinal, so a template "
            "whose refs span more than that collides with the next one:\n  "
            + "\n  ".join(sorted(clashes))
        )


def _resolve_nets(
    spec: BoardSpec,
) -> tuple[dict[str, dict[str, str]], list[ConnectionReport], list[str]]:
    """Decide the page-level name of every block-local net.

    Returns ``(renames, connection reports, notes)`` where
    ``renames[block id][local net] = page net``. A connection is authoritative:
    every port on it gets the connection's name, and if a block's local name
    already equals it the rename is a no-op. Anything the spec does not connect
    keeps its local name.
    """
    groups = _Groups()
    local_nets: dict[str, set[str]] = {}
    for block in spec.blocks:
        nets: set[str] = set()
        for component in block.template.components:
            for pin in component.pins:
                if pin["net"]:
                    nets.add(pin["net"])
        for wire in block.template.wires:
            if wire.net:
                nets.add(wire.net)
        for flag in block.template.flags:
            nets.add(flag.net)
        for label in block.template.labels:
            nets.add(label.net)
        local_nets[block.id] = nets
        for name in nets:
            groups.add((block.id, name))

    reports: list[ConnectionReport] = []
    notes: list[str] = []
    for connection in spec.connections:
        blocks_in = [block_id for block_id, _role in connection.ports]
        if len(set(blocks_in)) != len(blocks_in):
            raise AssemblyError(
                f"connection {connection.net!r} names a block twice; a connection "
                "joins *different* blocks"
            )
        joined: list[str] = []
        anchor: tuple[str, str] | None = None
        for block_id, role in connection.ports:
            block = spec.instance(block_id)
            assert block is not None  # load_board_spec validated the port
            port = block.template.port(role)
            assert port is not None
            node = (block_id, port.net)
            groups.add(node)
            if port.net not in local_nets[block_id]:
                notes.append(
                    f"{block_id}.{role}: the port names net {port.net!r}, which no "
                    "pin, wire, flag or label of the block carries"
                )
            if anchor is None:
                anchor = node
            else:
                groups.union(anchor, node)
            joined.append(f"{block_id}.{role}({port.net})")
        reports.append(
            ConnectionReport(net=connection.net, ports=list(connection.ports), joined=joined)
        )

    # --- the page name of every cluster, and the ambiguity check
    named: dict[tuple[str, str], str] = {}
    for connection in spec.connections:
        for block_id, role in connection.ports:
            block = spec.instance(block_id)
            assert block is not None
            port = block.template.port(role)
            assert port is not None
            named[groups.find((block_id, port.net))] = connection.net

    by_name: dict[str, list[tuple[str, str]]] = {}
    page_net_of_member: dict[tuple[str, str], str] = {}
    # A repeated template's **unconnected** nets are scoped to their instance
    # before the ambiguity check, not after: a copy of a block carries the same
    # net names as its twin — including its internal ones (`NET5`), which no
    # connection can join because they are not interfaces. Without this, placing
    # one template twice is reported as two circuits that must not share a name,
    # which is true of two *different* blocks and false of one block and its
    # copy. Ordinal 0 is left alone, so a one-instance-per-template spec is
    # exactly what 008a produced.
    repeated = repeated_templates(spec)
    ordinals = instance_ordinals(spec)
    for root, members in groups.clusters().items():
        page_net = named.get(root)
        if page_net is None:
            # An unconnected interface keeps the name the block's own geometry
            # carries; every member of the cluster agrees because a cluster is
            # either one node or one connection's nodes.
            page_net = members[0][1]
            if len({net for _block, net in members}) > 1:
                raise AssemblyError(
                    "internal error: a cluster without a connection spans "
                    f"{sorted(members)}"
                )
            owner = members[0][0]
            if repeated and ordinals[owner] > 0:
                page_net = f"{page_net}#{owner}"
        for member in members:
            by_name.setdefault(page_net, []).append(member)
            page_net_of_member[member] = page_net

    clashes: dict[str, list[list[tuple[str, str]]]] = {}
    for name, members in by_name.items():
        roots = {groups.find(member) for member in members}
        if len(roots) > 1:
            clashes.setdefault(name, [sorted({m for m in members if groups.find(m) == r}) for r in roots])
    if clashes:
        rendered = []
        for name, sides in sorted(clashes.items()):
            for side in sides:
                rendered.append(
                    f"  net {name!r}: " + ", ".join(f"{b}.{n}" for b, n in side)
                )
        raise AssemblyError(
            "two separate circuits would end up with the same page net name; a "
            "connection must join them, or one must be renamed. Rename the "
            "template's parameter/port or add a connection:\n" + "\n".join(rendered)
        )

    renames: dict[str, dict[str, str]] = {}
    for block in spec.blocks:
        # One source of truth for the page name of every block-local net: the
        # pass above already decided it (including the instance scoping), so the
        # name a wire is drawn with cannot drift from the name the ambiguity
        # check judged.
        renames[block.id] = {
            name: page_net_of_member[(block.id, name)]
            for name in local_nets[block.id]
        }
    return renames, reports, notes


#: How far a synthesised rail flag sits from the pin endpoint it names, along
#: the outward axis. One routing cell (`engines.layout.GRID`), which is the
#: lattice every other placement in the pipeline snaps to.
RAIL_STUB = 5.0


def _block_pin_endpoints(
    template: BlockTemplate, component: BlockComponent
) -> dict[str, list[Point]]:
    """Block-local **file**-space endpoints of one component's pins, by net.

    ``transform_point`` (``core.geometry``) is the one rotation convention in
    the project — the same call the parsers and the replay use — so a rotated
    or mirrored placement lands its pins exactly where the draw chain will put
    them. Note the space: this returns **file** coordinates, whereas the
    replay's own helper converts to canvas in the same breath; the assembler
    works in file space throughout, so the negation there must not be copied.
    """
    symbol = template.symbols.get(component.symbol)
    if symbol is None:
        return {}
    out: dict[str, list[Point]] = {}
    for pin in component.pins:
        # An unconnected pin carries the empty net name, and it must not become
        # a net: naming it would put an anonymous flag or label on the page.
        # `_resolve_nets` skips exactly these pins for the same reason.
        if not pin["net"]:
            continue
        offset = symbol.offsets.get(pin["number"])
        if offset is None:
            continue
        x, y = transform_point(
            offset[0],
            offset[1],
            rotation=component.rotation,
            mirror=component.mirror,
            ox=component.x,
            oy=component.y,
        )
        out.setdefault(pin["net"], []).append((x, y))
    return out


def _extreme_endpoint(points: list[Point], net_class: str) -> Point:
    """The endpoint a port's own anchor sits on, deterministically.

    A rail resolves to the top (power) or bottom (ground) endpoint of its net —
    the same rule the stub direction uses — with ties broken by smallest x so
    that a block with two pins at the same height does not resolve differently
    between runs. A signal has no up or down, so it resolves to smallest x
    (then smallest y), which is "the leftmost thing this net touches".
    """
    if net_class == "power":
        return min(points, key=lambda p: (-p[1], p[0]))
    if net_class == "gnd":
        return min(points, key=lambda p: (p[1], p[0]))
    return min(points, key=lambda p: (p[0], p[1]))


def _synthesise_anchors(
    block_id: str,
    template: BlockTemplate,
    delta: Point,
    renames: dict[str, str],
    page: PageLayout,
    report: list[str],
    notes: list[str],
) -> dict[str, Point]:
    """Name every pin endpoint of a geometry-less block, and say where.

    A ``datasheet-extract`` / ``textbook`` block has no wires and no flags, so
    without this its pins are electrically real but visually anonymous — a
    reader sees three parts and no idea which net is which. There is nothing to
    invent about the *glyph*: the editor resolves a flag from ``kind`` + ``net``
    and a signal name from a net label. What each anchor needs is a position,
    and the pin endpoints supply it.

    Every endpoint gets a name, per the ruling — a rail endpoint gets a one-cell
    stub plus a power/ground flag at its far end (so the flag hangs off the pin
    the way a drawn one does, rather than sitting on top of it), a signal
    endpoint gets a net label right at the tip. An anchor that lands inside
    another part's body is **noted, not refused**: the block's author placed
    those parts and this pass must not overrule a signed layout — a collision
    here is a readability judgement for a human, which is what the real-host
    smoke is for.

    Returns the resolved anchor position per port role.
    """
    # --- every endpoint of every component, in block-local file space
    by_net: dict[str, list[Point]] = {}
    for component in template.components:
        for net, points in _block_pin_endpoints(template, component).items():
            by_net.setdefault(net, []).extend(points)
    if not by_net:
        return {}

    net_classes = {port.net: port.net_class for port in template.interface}
    body_boxes = _component_boxes(template)

    # Counts taken on entry so the report line can attribute what *this* block
    # added; reading the page totals would credit this block with every anchor
    # an earlier block already put down.
    flags_before = len(page.flags)
    labels_before = len(page.labels)

    placed: dict[str, Point] = {}
    for net in sorted(by_net):
        page_net = renames.get(net, net)
        endpoints = sorted(set(by_net[net]))
        net_class = net_classes.get(net, "signal")
        for local_x, local_y in endpoints:
            x, y = local_x + delta[0], local_y + delta[1]
            if net_class == "signal":
                page.labels.append(NetLabelAnchor(net=page_net, x=x, y=y, rotation=0.0))
            else:
                # A rail flag reads as attached when it hangs off the pin, so
                # the stub runs outward: up from the topmost points, down from
                # the bottom ones. `+y` is up in file space (the y-up
                # convention the whole parser layer uses).
                outward = RAIL_STUB if net_class == "power" else -RAIL_STUB
                page.wires.append(
                    WireRun(
                        group=f"{block_id}:anchor:{net}:{local_x:.0f},{local_y:.0f}",
                        net=page_net,
                        points=[(x, y), (x, y + outward)],
                    )
                )
                flag_x, flag_y = x, y + outward
                page.flags.append(
                    PlacedFlag(
                        net=page_net,
                        kind="Power" if net_class == "power" else "Ground",
                        x=flag_x,
                        y=flag_y,
                        rotation=0.0,
                        mirror=False,
                        # Empty on purpose: the symbol uuid only feeds the
                        # annotation-box prediction, and the editor resolves the
                        # glyph from kind + net. Verified by
                        # `tools/_probe_flag_anchor.py`.
                        symbol_uuid="",
                    )
                )

    # --- ports: the anchor is synthesised, and it doubles as the port's place
    for port in template.interface:
        points = by_net.get(port.net)
        if not points:
            continue
        endpoint = _extreme_endpoint(points, port.net_class)
        page_net = renames.get(port.net, port.net)
        if port.net_class == "signal":
            resolved = (endpoint[0] + delta[0], endpoint[1] + delta[1])
        else:
            outward = RAIL_STUB if port.net_class == "power" else -RAIL_STUB
            resolved = (endpoint[0] + delta[0], endpoint[1] + delta[1] + outward)
        placed[port.role] = resolved

    for role, (ax, ay) in sorted(placed.items()):
        for ref, box in body_boxes:
            if box[0] <= ax <= box[2] and box[1] <= ay <= box[3]:
                notes.append(
                    f"block {block_id}: the synthesised anchor for {role!r} at "
                    f"({ax:.0f}, {ay:.0f}) falls inside {ref}'s body; the block's "
                    "author placed these parts, so the layout is kept as signed "
                    "and the readability of this anchor is a real-host question"
                )
    report.append(
        f"  block {block_id}: no template geometry, so {len(by_net)} net(s) were "
        f"named by synthesised anchors ({sum(len(p) for p in by_net.values())} "
        f"pin endpoint(s): {len(page.flags) - flags_before} flag(s), "
        f"{len(page.labels) - labels_before} label(s))"
    )
    return placed


def _component_boxes(
    template: BlockTemplate,
) -> list[tuple[str, tuple[float, float, float, float]]]:
    """Each component's block-local drawn box, for the anchor-collision note.

    Built from the symbol's measured ``body`` when it has one and from its pin
    offsets otherwise, which is the same fallback the replay's own box helper
    uses — an anchor judgement made against a different extent than the one the
    page is drawn with would not mean anything.
    """
    boxes: list[tuple[str, tuple[float, float, float, float]]] = []
    for component in template.components:
        symbol = template.symbols.get(component.symbol)
        if symbol is None:
            continue
        corners: list[tuple[float, float]] = []
        if symbol.body is not None:
            b = symbol.body
            corners = [(b[0], b[1]), (b[0], b[3]), (b[2], b[1]), (b[2], b[3])]
        else:
            corners = list(symbol.offsets.values())
        if not corners:
            continue
        placed = [
            transform_point(
                cx,
                cy,
                rotation=component.rotation,
                mirror=component.mirror,
                ox=component.x,
                oy=component.y,
            )
            for cx, cy in corners
        ]
        xs = [p[0] for p in placed]
        ys = [p[1] for p in placed]
        boxes.append((component.ref, (min(xs), min(ys), max(xs), max(ys))))
    return boxes


def assemble(spec: BoardSpec) -> AssembledDesign:
    """Compose a :class:`BoardSpec` into a design the draw chain can execute."""
    _check_designators(spec)
    # `load_board_spec` validates the assignments up front, but `assemble` also
    # accepts a hand-constructed BoardSpec (tests, future callers), and a
    # parameter nobody binds would otherwise be dropped in silence — the one
    # failure mode a spec-with-numbers exists to prevent.
    for key in spec.params:
        head, _, tail = key.partition(".")
        spec.parameter_value(head, tail)
    renames, connections, notes = _resolve_nets(spec)
    # Per-instance designators (008c item 6): a template used twice numbers its
    # parts apart, and the *page* designator is what every later step uses — the
    # model, the page layout and the clash check read the same map.
    designators = designator_map(spec)
    ordinals = instance_ordinals(spec)
    for identity, ids in sorted(repeated_templates(spec).items()):
        notes.append(
            f"the template {identity} is placed {len(ids)} times "
            f"({', '.join(ids)}); instance ordinals are "
            + ", ".join(f"{bid}={ordinals[bid]}" for bid in ids)
            + f", and a derived designator adds {DESIGNATOR_STRIDE} per ordinal"
        )
        for block_id in ids:
            if ordinals[block_id] == 0:
                continue
            scoped = sorted(
                self_name
                for self_name in renames.get(block_id, {})
                if renames[block_id][self_name] == f"{self_name}#{block_id}"
            )
            if scoped:
                notes.append(
                    f"block {block_id}: {len(scoped)} net(s) the spec does not "
                    "connect are scoped to this instance ("
                    + ", ".join(f"{n}->{renames[block_id][n]}" for n in scoped)
                    + "), because a copy of a block carries the same net names as "
                    "its twin"
                )

    model = DesignModel()
    page = PageLayout(
        sheet_attrs=dict(spec.sheet_attrs),
        sheet_origin=spec.sheet_origin,
    )
    offsets: dict[str, dict[str, Point]] = {}
    symbol_defs: dict[str, dict[str, Point]] = {}
    bodies: dict[str, tuple[float, float, float, float]] = {}
    ports: list[PortPlacement] = []
    report: list[str] = []

    for block in spec.blocks:
        template = block.template
        # The template's local origin (0, 0) *is* the block's origin — the cut
        # stored absolute-minus-origin — so putting the block at `at` is a plain
        # addition. `at - origin_file` would double-count the cut offset, which
        # is what the first assembler did (correct model, geometry 240 units
        # off the page).
        delta = (block.at[0], block.at[1])

        def moved(x: float, y: float) -> Point:
            return (x + delta[0], y + delta[1])

        derived = sorted(
            (ref, page_ref)
            for ref, page_ref in designators[block.id].items()
            if ref != page_ref
        )
        if derived:
            report.append(
                f"  instance {ordinals[block.id]} of {template_identity(block)}: "
                + ", ".join(f"{ref}->{page_ref}" for ref, page_ref in derived)
            )
        report.append(
            f"block {block.id} <- {template.name} at {block.at} "
            f"(cut at {template.origin_file}"
            + (
                ""
                if (block.at[0], block.at[1]) == template.origin_file
                else f", moved by ({delta[0] - template.origin_file[0]:+.0f}, "
                f"{delta[1] - template.origin_file[1]:+.0f})"
            )
            + f") : {len(template.components)} parts, {len(template.wires)} wires"
        )

        # --- symbols: geometry travels with the block, positions do not
        for uuid, symbol in template.symbols.items():
            symbol_defs.setdefault(uuid, dict(symbol.offsets))
            if symbol.body is not None:
                bodies.setdefault(uuid, symbol.body)

        # --- components
        for component in template.components:
            x, y = moved(component.x, component.y)
            value = ""
            bound = component.params.get("value")
            if bound:
                value = spec.parameter_value(block.id, bound)
            props: dict[str, object] = {}
            if component.device.name:
                props["device_name"] = component.device.name
            if component.device.device_uuid:
                props["place_device_uuid"] = component.device.device_uuid
            if component.device.library_uuid:
                props["place_library_uuid"] = component.device.library_uuid
            if component.device.expect_footprint:
                props["expect_footprint"] = component.device.expect_footprint
            if component.device.provenance:
                props["device_provenance"] = component.device.provenance
            page_ref = designators[block.id][component.ref]
            model.components[page_ref] = Component(
                uid=component.symbol,
                designator=page_ref,
                value=value,
                footprint=component.footprint,
                lcsc_part=component.device.lcsc,
                props=props,
                pins=[
                    Pin(
                        number=pin["number"],
                        name=pin["name"],
                        net=renames[block.id].get(pin["net"], pin["net"]) or None,
                    )
                    for pin in component.pins
                ],
            )
            offsets[page_ref] = dict(template.symbols[component.symbol].offsets)
            page.parts.append(
                PlacedPart(
                    designator=page_ref,
                    x=x,
                    y=y,
                    rotation=component.rotation,
                    mirror=component.mirror,
                    symbol_uuid=component.symbol,
                )
            )

        # --- geometry, translated and renamed
        for index, wire in enumerate(template.wires):
            page.wires.append(
                WireRun(
                    # A unique group per run: the replay groups runs by net and
                    # falls back to `__net_<group>` for an unnamed one, so two
                    # runs sharing a group would be merged into one route.
                    group=f"{block.id}:{index}",
                    net=renames[block.id].get(wire.net, wire.net),
                    points=[moved(x, y) for x, y in wire.points],
                )
            )
        for flag in template.flags:
            x, y = moved(flag.x, flag.y)
            page.flags.append(
                PlacedFlag(
                    net=renames[block.id].get(flag.net, flag.net),
                    kind=flag.kind,
                    x=x,
                    y=y,
                    rotation=flag.rotation,
                    mirror=flag.mirror,
                    symbol_uuid=flag.symbol,
                )
            )
        for label in template.labels:
            x, y = moved(label.x, label.y)
            page.labels.append(
                NetLabelAnchor(
                    net=renames[block.id].get(label.net, label.net),
                    x=x,
                    y=y,
                    rotation=label.rotation,
                )
            )

        # --- ports: recorded, and named — by one of the two paths (2026-09-17)
        #
        # Which path applies is decided by whether *this template* carries
        # geometry, not by its provenance label: a block with wires or flags
        # replays the anchors its cut saw, and a block with none has its anchors
        # synthesised from its own pin endpoints. See the module docstring.
        has_geometry = bool(template.wires or template.flags or template.labels)
        connected = {
            (block_id, role)
            for connection in spec.connections
            for block_id, role in connection.ports
        }
        if not has_geometry:
            synthesised = _synthesise_anchors(
                block.id,
                template,
                delta,
                renames.get(block.id, {}),
                page,
                report,
                notes,
            )
        else:
            synthesised = {}
        for port in template.interface:
            page_net = renames[block.id].get(port.net, port.net)
            if not has_geometry:
                # The anchor was synthesised; the port records where it went.
                # A port whose net has no pin endpoint in this block has nothing
                # to hang a name on, and saying so is better than naming it at a
                # made-up point.
                if port.role not in synthesised:
                    notes.append(
                        f"port {block.id}.{port.role}: no pin endpoint carries "
                        f"{port.net!r} in this block, so no anchor could be "
                        "synthesised for it"
                    )
                    continue
                x, y = synthesised[port.role]
            else:
                x, y = moved(port.position[0], port.position[1])
                at_position = {
                    "signal": [
                        label
                        for label in page.labels
                        if label.net == page_net
                        and (label.x, label.y) == (x, y)
                    ],
                    "power": [
                        flag
                        for flag in page.flags
                        if flag.net == page_net and (flag.x, flag.y) == (x, y)
                    ],
                }["signal" if port.is_signal else "power"]
                if not at_position:
                    if port.is_signal:
                        # 岳翔宇's R2: between blocks, a net label and never a
                        # port. The template has the interface but no anchor for
                        # it, so the name is drawn here — a label anchor, which
                        # the replay turns into the configured signal-name
                        # primitive.
                        page.labels.append(
                            NetLabelAnchor(net=page_net, x=x, y=y, rotation=0.0)
                        )
                        report.append(
                            f"  port {block.id}.{port.role}: no anchor in the "
                            f"template; placed a net label for {page_net!r} at "
                            f"({x:.0f}, {y:.0f})"
                        )
                    else:
                        raise AssemblyError(
                            f"port {block.id}.{port.role} is {port.net_class} and "
                            f"has no {'ground' if port.net_class == 'gnd' else 'power'} "
                            f"flag at ({x:.0f}, {y:.0f}) to name it. This template "
                            "carries geometry, so its anchors are the ones its cut "
                            "saw: a missing flag is a defect in the template (or in "
                            "the cut that produced it), not something this pass may "
                            "invent a point for. A geometry-less block's anchors are "
                            "synthesised instead — see the module docstring."
                        )
            ports.append(
                PortPlacement(
                    block=block.id,
                    role=port.role,
                    net_class=port.net_class,
                    local_net=port.net,
                    page_net=page_net,
                    position=(x, y),
                    connected=(block.id, port.role) in connected,
                )
            )
            if (block.id, port.role) not in connected:
                notes.append(
                    f"port {block.id}.{port.role} is not named by any connection; it "
                    f"keeps its own net name {page_net!r}"
                )

    # --- the spec netlist: nets from the pins, in canonical order
    nets: dict[str, Net] = {}
    for designator in sorted(model.components):
        for pin in model.components[designator].pins:
            if not pin.net:
                continue
            entry = nets.setdefault(pin.net, Net(name=pin.net))
            member = (designator, pin.number)
            if member not in entry.pins:
                entry.pins.append(member)
    model.nets = nets

    report.append(
        f"assembled {len(model.components)} parts, {len(model.nets)} nets, "
        f"{len(page.wires)} wire runs, {len(page.flags)} flags, {len(page.labels)} labels"
    )
    design = AssembledDesign(
        name=spec.name,
        model=model,
        page=page,
        offsets=offsets,
        symbol_defs=symbol_defs,
        bodies=bodies,
        ports=ports,
        connections=connections,
        report=report,
        notes=notes,
    )
    extent = design.bbox_file()
    if extent is not None:
        report.append(
            f"content extent (file coordinates): {extent[0]:.0f},{extent[1]:.0f}"
            f" - {extent[2]:.0f},{extent[3]:.0f}"
        )
    return design


def assembly_lines(design: AssembledDesign) -> list[str]:
    """The gate's view of an assembly: what was placed, and how it is wired."""
    lines = [f"  {line}" for line in design.report]
    if design.connections:
        lines.append("  connections (page net <- ports):")
        for connection in design.connections:
            lines.append(f"    {connection.net:8} <- {', '.join(connection.joined)}")
    if design.ports:
        lines.append("  ports:")
        for port in design.ports:
            mark = "" if port.connected else "  (not connected by the spec)"
            renamed = (
                ""
                if port.local_net == port.page_net
                else f" [{port.local_net} -> {port.page_net}]"
            )
            lines.append(
                f"    {port.block}.{port.role:8} {port.net_class:6} "
                f"at ({port.position[0]:.0f},{port.position[1]:.0f}){renamed}{mark}"
            )
    for note in design.notes:
        lines.append(f"  note: {note}")
    return lines


def print_assembly(design: AssembledDesign) -> None:
    """Print :func:`assembly_lines` (the gate's view of an assembly)."""
    for line in assembly_lines(design):
        print(line)


__all__ = [
    "AssembledDesign",
    "AssemblyError",
    "ConnectionReport",
    "PortPlacement",
    "assemble",
    "assembly_lines",
    "print_assembly",
]
