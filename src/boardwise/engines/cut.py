"""Cut a block template out of a golden page (task 008a, work item 2).

The cut is the mechanical end of the three template sources the architecture
lists (008 constitution item 3: textbook / datasheet-extract / **board-extract**).
It is deliberately dumb: a designer names the parts and draws a box, and the
tool moves exactly what is inside that box into a block template — with the
coordinates normalised to the block's own origin so the block can be placed
anywhere.

What it refuses to do, and why that matters more than what it does:

* **It does not guess a boundary.** A wire run that lies partly inside the box
  is an error, not a silently-included-or-dropped run: including it would drag
  a stub into whatever block ends up next door, and dropping it would lose
  copper the connectivity pass has already counted. The message says which run
  and where it leaves, so the designer moves the line.
* **It does not invent ports.** A port is a label or flag that sits inside the
  box *and* names a net with at least one member outside the block — i.e. the
  block's interface, derived from what the board actually says. A net that
  crosses the boundary with no anchor of its own therefore gets **no port** and
  a note; task 008a is explicit that the boundary carries what it carries and
  the rest is a human's to fill in.
* **It does not invent parameters.** A part whose source value is empty has
  nothing to parameterise; the rest become block parameters whose constraint is
  inferred from evidence (a ``Ω``, a trailing farad, a device title beginning
  ``Res``) and reported. When the evidence is ambiguous the constraint is
  ``free_text`` and the note says so, because a wrong constraint is worse than
  none — it *claims* a check nobody performed.

Coordinates in the produced template are block-local file coordinates; see
:mod:`boardwise.core.blocks`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from boardwise.core.blocks import (
    BlockComponent,
    BlockError,
    BlockParam,
    BlockPort,
    BlockSymbol,
    BlockTemplate,
    DeviceBinding,
    TemplateFlag,
    TemplateLabel,
    TemplateWire,
    net_class_of,
    template_to_json,
)
from boardwise.core.overrides import AppliedOverrides
from boardwise.parsers.schematic import (
    PlacedPart,
    build_schematic_model,
    collect_page_layout,
    collect_symbol_details,
)

Point = tuple[float, float]

#: A device title that announces a resistor — this library's own convention
#: (``Res_0402``), used only to *classify* an existing value, never to resolve
#: a part.
_DEVICE_TITLE_RESISTOR = re.compile(r"^res\b|^res[_\- ]", re.IGNORECASE)
#: A footprint name that announces a resistor package (``R0402``).
_FOOTPRINT_RESISTOR = re.compile(r"^R[0-9]{4}", re.IGNORECASE)
#: A value ending in a farad unit, after an optional SI prefix.
_FARAD_TAIL = re.compile(r"[0-9]\s*(p|n|u|µ|μ|m|k|K)?\s*[Ff]$")
_OHM = re.compile(r"Ω|ohm", re.IGNORECASE)


class CutError(BlockError):
    """The requested cut cannot be made as asked."""


@dataclass
class CutOutcome:
    """The template plus the lines a human wants to read about how it was cut."""

    template: BlockTemplate
    report: list[str] = field(default_factory=list)

    def to_json(self) -> dict:
        return template_to_json(self.template)


def _inside(
    box: tuple[float, float, float, float], point: Point
) -> bool:
    return box[0] <= point[0] <= box[2] and box[1] <= point[1] <= box[3]


def infer_constraint(
    value: str, footprint: str = "", device_name: str = ""
) -> tuple[str, str]:
    """``(constraint, reason)`` for one component value, from evidence only.

    Ordering is evidence-first: a device title or package that *says* resistor
    outranks a value shape, because ``104`` is a resistor's marking and a
    capacitor's marking at once and only the package breaks the tie.
    """
    text = (value or "").strip()
    if not text:
        return ("free_text", "no value in the source; nothing to parameterise")
    if _DEVICE_TITLE_RESISTOR.search(device_name) or _FOOTPRINT_RESISTOR.match(footprint):
        return ("resistor_value", f"device/package says resistor ({device_name or footprint})")
    if _FARAD_TAIL.search(text):
        return ("capacitor_value", "the value ends in a farad unit")
    if _OHM.search(text):
        return ("resistor_value", "the value carries an ohm unit")
    return ("free_text", "no evidence for a numeric constraint; set it by hand")


def _device_binding(
    component, symbol_detail, override
) -> DeviceBinding:
    """The library binding for one placed part, with the sidecar folded in.

    The golden's own ``device_uuid`` prop is a *file-local* document uuid
    (measured: "not found in the library"), so a placeable pair only ever comes
    from an override; the raw fingerprint is deliberately not copied.
    """
    fields = override.fields if override is not None else {}
    return DeviceBinding(
        lcsc=fields.get("lcsc", component.lcsc_part if component else ""),
        keyword="",
        device_uuid=fields.get("place_device_uuid", ""),
        library_uuid=fields.get("place_library_uuid", ""),
        expect_footprint=fields.get("expect_footprint", ""),
        name=(component.props.get("device_name", "") if component else "")
        or (symbol_detail.title if symbol_detail else ""),
        provenance=(override.provenance if override is not None else ""),
    )


def _part_box(part: PlacedPart, detail, offsets: dict[str, Point], origin: Point) -> tuple:
    """The part's drawn box at its own placement, in block-local file space.

    Mirrors ``engines.replay.part_box``: the measured drawn extent when the
    symbol has one, the pin extents otherwise, rotated by the instance. Only the
    *canvas* conversion is left to the replay — this is file space throughout.
    """
    from boardwise.core.geometry import transform_point

    if detail is not None and detail.body is not None:
        body = detail.body
        corners = [(body[0], body[1]), (body[0], body[3]), (body[2], body[1]), (body[2], body[3])]
    else:
        corners = list(offsets.values())
    xs: list[float] = []
    ys: list[float] = []
    for dx, dy in corners:
        fx, fy = transform_point(
            dx, dy, rotation=part.rotation, mirror=part.mirror, ox=part.x, oy=part.y
        )
        xs.append(fx - origin[0])
        ys.append(fy - origin[1])
    if not xs:
        return (part.x - origin[0], part.y - origin[1], part.x - origin[0], part.y - origin[1])
    return (min(xs), min(ys), max(xs), max(ys))


def extract_block(
    golden: str | Path,
    *,
    name: str,
    description: str = "",
    designators: list[str],
    bbox: tuple[float, float, float, float],
    note: str = "",
    overrides: AppliedOverrides | None = None,
    constraints: dict[str, str] | None = None,
) -> CutOutcome:
    """Cut one block template out of ``golden``.

    ``designators`` are the parts the block owns; ``bbox`` is the designer's
    boundary in **absolute file coordinates**. ``overrides`` is the golden
    corrections sidecar (task 006b §G.3): the fixture is evidence and is never
    edited, so corrections are folded into the template's device bindings and
    parameter defaults, each carrying the sidecar's provenance string.
    ``constraints`` overrides the inferred constraint of a parameter by
    component ref, for the values the inference refuses to classify.
    """
    golden_path = Path(golden)
    model = build_schematic_model(golden_path)
    page = collect_page_layout(golden_path)
    details = collect_symbol_details(golden_path)

    wanted = [str(des) for des in designators]
    if not wanted:
        raise CutError("no designators given — a block with no parts places nothing")
    duplicated = sorted({d for d in wanted if wanted.count(d) > 1})
    if duplicated:
        raise CutError(f"designator(s) listed twice: {', '.join(duplicated)}")

    parts_by_designator = {part.designator: part for part in page.parts}
    missing = [d for d in wanted if d not in parts_by_designator]
    if missing:
        raise CutError(
            f"{golden_path}: no such part(s) on the page: {', '.join(missing)}"
        )

    origin: Point = (bbox[0], bbox[1])
    owned = set(wanted)
    report: list[str] = []
    template_notes: list[str] = []
    override_by_designator = {
        item.designator: item for item in (overrides.items if overrides is not None else [])
    }

    # --- the boundary must own its parts
    outside = []
    for des in wanted:
        part = parts_by_designator[des]
        detail = details.get(part.symbol_uuid)
        offsets = {n: p for n, p in (detail.offsets if detail else {}).items()}
        for corner in (
            (part.x, part.y),
            _part_box(part, detail, offsets, (0.0, 0.0))[:2],
            _part_box(part, detail, offsets, (0.0, 0.0))[2:],
        ):
            if not _inside(bbox, corner):
                outside.append(f"{des} at {corner}")
                break
    if outside:
        raise CutError(
            "the bounding box does not contain: "
            + "; ".join(outside)
            + " — widen it or leave the part out"
        )

    # --- geometry: everything inside the box, and *only* what is fully inside
    wires: list[TemplateWire] = []
    straddling: list[str] = []
    for run in page.wires:
        inside = [p for p in run.points if _inside(bbox, p)]
        if not inside:
            continue
        if len(inside) != len(run.points):
            leaving = [p for p in run.points if not _inside(bbox, p)]
            straddling.append(
                f"wire net={run.net or '(unnamed)'} points={run.points} leaves at {leaving}"
            )
            continue
        wires.append(
            TemplateWire(
                net=run.net,
                points=[(x - origin[0], y - origin[1]) for x, y in run.points],
            )
        )
    if straddling:
        raise CutError(
            "the boundary cuts through "
            + f"{len(straddling)} wire run(s); a run that leaves the box cannot be "
            "assigned to a block without dragging or losing copper. Move the "
            "boundary clear of it:\n  " + "\n  ".join(straddling)
        )

    flags = [
        TemplateFlag(
            net=flag.net,
            kind=flag.kind,
            x=flag.x - origin[0],
            y=flag.y - origin[1],
            rotation=flag.rotation,
            mirror=flag.mirror,
            symbol=flag.symbol_uuid,
        )
        for flag in page.flags
        if _inside(bbox, (flag.x, flag.y))
    ]
    labels = [
        TemplateLabel(
            net=label.net,
            x=label.x - origin[0],
            y=label.y - origin[1],
            rotation=label.rotation,
        )
        for label in page.labels
        if _inside(bbox, (label.x, label.y))
    ]

    # --- components, their pins and their parameters
    components: list[BlockComponent] = []
    params: list[BlockParam] = []
    symbol_uuids: set[str] = set()
    for des in wanted:
        part = parts_by_designator[des]
        component = model.components.get(des)
        symbol_uuid = part.symbol_uuid or (component.uid if component else "")
        if not symbol_uuid:
            raise CutError(f"{des}: the part has no symbol uuid; cannot cut its geometry")
        symbol_uuids.add(symbol_uuid)
        detail = details.get(symbol_uuid)
        if detail is None or not detail.offsets:
            raise CutError(
                f"{des}: symbol {symbol_uuid!r} has no pin offsets in this file — "
                "the block could not place it"
            )

        override = override_by_designator.get(des)
        value = (override.fields["value"] if override and "value" in override.fields else "")
        value = value or (component.value if component else "")

        binds: dict[str, str] = {}
        if value:
            param_name = f"{des.lower()}_value"
            constraint, reason = infer_constraint(
                value,
                component.footprint if component else "",
                component.props.get("device_name", "") if component else "",
            )
            if constraints and des in constraints:
                constraint = constraints[des]
                reason = "set by the caller"
            if constraint == "free_text":
                template_notes.append(
                    f"{des}: value {value!r} has no inferred constraint ({reason}); "
                    "it is a free-text parameter"
                )
            params.append(
                BlockParam(
                    name=param_name,
                    role=f"{des} value",
                    default=value,
                    constraint=constraint,
                    provenance=(
                        override.provenance
                        if override is not None and "value" in override.fields
                        else ""
                    ),
                )
            )
            binds["value"] = param_name
            report.append(
                f"param {param_name} = {value!r} ({constraint}) — {reason}"
                + (
                    " [corrected by the sidecar]"
                    if override is not None and "value" in override.fields
                    else ""
                )
            )

        components.append(
            BlockComponent(
                ref=des,
                symbol=symbol_uuid,
                x=part.x - origin[0],
                y=part.y - origin[1],
                rotation=part.rotation,
                mirror=part.mirror,
                device=_device_binding(component, detail, override),
                footprint=(component.footprint if component else ""),
                params=binds,
                pins=[
                    {
                        "number": pin.number,
                        "name": pin.name,
                        "net": pin.net or "",
                    }
                    for pin in (component.pins if component else [])
                ],
            )
        )

    # --- symbols: every symbol this block places, including the flag glyphs
    symbols: dict[str, BlockSymbol] = {}
    for uuid in sorted(symbol_uuids | {flag.symbol for flag in flags if flag.symbol}):
        detail = details.get(uuid)
        if detail is None:
            raise CutError(f"symbol {uuid!r} is missing from the file's symbol documents")
        symbols[uuid] = BlockSymbol(
            uuid=uuid,
            offsets=dict(detail.offsets),
            body=detail.body,
            pin_names=dict(detail.pin_names),
        )

    # --- ports: the nets that leave the block, anchored where the board says
    flag_kinds = {flag.net: flag.kind for flag in page.flags}
    anchor_by_net: dict[str, list[Point]] = {}
    for label in labels:
        anchor_by_net.setdefault(label.net, []).append((label.x, label.y))
    for flag in flags:
        anchor_by_net.setdefault(flag.net, []).append((flag.x, flag.y))

    local_nets: list[str] = []
    for component in components:
        for pin in component.pins:
            net = pin["net"]
            if net and net not in local_nets:
                local_nets.append(net)
    for label in labels:
        if label.net not in local_nets:
            local_nets.append(label.net)
    for flag in flags:
        if flag.net not in local_nets:
            local_nets.append(flag.net)

    # Both sides are block-local already (`flags` / `labels` were normalised
    # above), so the centre has to be normalised the same way — subtracting the
    # origin twice is how the first cut produced ports at x = -384.
    centre = ((bbox[0] + bbox[2]) / 2 - origin[0], (bbox[1] + bbox[3]) / 2 - origin[1])
    interface: list[BlockPort] = []
    for net in local_nets:
        members = model.nets.get(net)
        if members is None:
            continue
        if not any(des not in owned for des, _pin in members.pins):
            continue  # entirely inside the block: an internal net, not an interface
        anchors = anchor_by_net.get(net)
        if not anchors:
            template_notes.append(
                f"net {net!r} leaves the block but no label or flag of it sits inside "
                "the boundary — no port was invented for it; add one by hand if the "
                "interface is real"
            )
            continue
        nearest = min(
            anchors,
            key=lambda p: ((p[0] - centre[0]) ** 2 + (p[1] - centre[1]) ** 2, p),
        )
        interface.append(
            BlockPort(
                role=net,
                net=net,
                net_class=net_class_of(net, flag_kinds),
                position=(nearest[0], nearest[1]),
            )
        )

    template = BlockTemplate(
        name=name,
        description=description,
        provenance_kind="board-extract",
        provenance_source=str(golden_path),
        provenance_note=note,
        origin_file=origin,
        bbox_file=bbox,
        components=components,
        symbols=symbols,
        interface=interface,
        params=params,
        wires=wires,
        flags=flags,
        labels=labels,
        notes=template_notes,
    )

    report.insert(
        0,
        f"block {name}: {len(components)} parts, {len(wires)} wire runs, "
        f"{len(flags)} flags, {len(labels)} labels, {len(interface)} ports "
        f"from bbox {bbox}",
    )
    report.append(
        "ports: "
        + (
            ", ".join(f"{port.role}({port.net_class})" for port in interface)
            if interface
            else "(none)"
        )
    )
    return CutOutcome(template=template, report=report)


def recut(
    golden: str | Path,
    template: BlockTemplate,
    *,
    overrides: AppliedOverrides | None = None,
) -> CutOutcome:
    """Re-cut a template from its own provenance.

    Everything the cut needs — the designators, the boundary, the constraints —
    is recorded *in* the template, so a committed block can be re-derived from
    the golden file it names. That is what makes "the template is a faithful
    extract of board X at region Y" a checkable claim rather than a comment: the
    regeneration is deterministic and the test asserts the bytes match.

    **Only a board-extract can be re-cut.** A `datasheet-extract` or `textbook`
    block has no source board and no boundary to draw, so there is nothing here
    to regenerate and no golden to compare against. That is not a limitation to
    work around — it is the distinction between the two kinds of template, and
    it is what lets the committed-block guard reason about which files it owns
    by *inspecting them* rather than by keeping a list of names up to date.
    """
    if template.provenance_kind != "board-extract":
        raise CutError(
            f"{template.name}: only a board-extract can be re-cut, but this "
            f"template's provenance.kind is {template.provenance_kind!r}. A "
            "datasheet-extract or textbook block has no source board to cut "
            "from — it is authored, not extracted, and the generic solver "
            "places it at assembly time. Nothing was changed."
        )
    constraints: dict[str, str] = {}
    for component in template.components:
        bound = component.params.get("value")
        if not bound:
            continue
        param = template.param(bound)
        if param is not None:
            constraints[component.ref] = param.constraint
    return extract_block(
        golden,
        name=template.name,
        description=template.description,
        designators=[component.ref for component in template.components],
        bbox=template.bbox_file,
        note=template.provenance_note,
        overrides=overrides,
        constraints=constraints,
    )


def write_block(outcome: CutOutcome, path: str | Path) -> Path:
    """Write a cut template to disk as JSON (one file per block)."""
    import json

    file = Path(path)
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(
        json.dumps(outcome.to_json(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return file


__all__ = [
    "CutError",
    "CutOutcome",
    "extract_block",
    "infer_constraint",
    "recut",
    "write_block",
]
