"""The assembly engine: blocks + spec -> a drawable design (task 008a, item 3/4).

Two properties carry the task's claim. The **round trip** proves the cut and the
assembler agree about geometry: putting every block back where it was cut from
reproduces the golden page's parts, wires, flags and labels exactly. The
**moved** spec proves the assembly is an assembly: the four blocks sit on a grid
of the spec's own choosing, the layout still lints clean, and the spec netlist
still matches the golden — i.e. block-to-block connectivity survives being
carried by net names rather than by copper.

The negative tests are the ones that would matter on a real board: a changed
parameter must show up as a difference, and the three ways an assembly can be
silently wrong (a duplicated designator, two circuits sharing a name, a power
port with nothing to name it) must all be refusals rather than quiet merges.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from boardwise.core.blocks import (
    SCHEMA_VERSION,
    BlockError,
    BlockInstance,
    BoardSpec,
    template_from_json,
)
from boardwise.core.compare import compare_models
from boardwise.core.overrides import apply_overrides, load_overrides
from boardwise.engines.assemble import AssemblyError, assemble
from boardwise.engines.layout import FRAME, Rect
from boardwise.engines.replay import replay_or_solver, sheet_frame_from_bbox

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "tests" / "fixtures" / "ch340_golden.epro2"
SIDECAR = ROOT / "tests" / "fixtures" / "ch340_golden.overrides.json"
SPEC = ROOT / "blocklib" / "specs" / "ch340g_usb_uart.json"

SHEET = Rect(0.0, 0.0, 1170.0, 825.0)


@pytest.fixture
def spec():
    """Fresh per test: several tests mutate a spec to model a wrong one."""
    from boardwise.core.blocks import load_board_spec

    return load_board_spec(SPEC)


@pytest.fixture
def design(spec):
    return assemble(spec)


@pytest.fixture(scope="module")
def corrected_golden():
    from boardwise.parsers.schematic import build_schematic_model

    model = build_schematic_model(GOLDEN)
    apply_overrides(model, load_overrides(SIDECAR))
    return model


def _plan(design):
    from boardwise.engines.generate import strip_dangling_nets

    frame = sheet_frame_from_bbox(SHEET, provenance="spec-declared")
    plan, source = replay_or_solver(
        strip_dangling_nets(design.model),
        design.page,
        frame,
        design.offsets,
        bodies=design.bodies,
    )
    assert source == "golden replay", source
    return plan, frame


# --------------------------------------------------------------------------
# the round trip
# --------------------------------------------------------------------------


def test_putting_the_blocks_back_reproduces_the_golden_page(spec, corrected_golden):
    from boardwise.parsers.schematic import collect_page_layout

    for block in spec.blocks:
        block.at = block.template.origin_file
    assembled = assemble(spec)
    golden = collect_page_layout(GOLDEN)

    assert compare_models(corrected_golden, assembled.model).is_empty, (
        "the cut/assemble round trip changed the netlist"
    )
    assert sorted(
        (p.designator, p.x, p.y, p.rotation, p.mirror, p.symbol_uuid)
        for p in assembled.page.parts
    ) == sorted(
        (p.designator, p.x, p.y, p.rotation, p.mirror, p.symbol_uuid) for p in golden.parts
    )
    assert sorted((w.net, tuple(w.points)) for w in assembled.page.wires) == sorted(
        (w.net, tuple(w.points)) for w in golden.wires
    )
    assert sorted(
        (f.net, f.kind, f.x, f.y, f.rotation, f.mirror) for f in assembled.page.flags
    ) == sorted((f.net, f.kind, f.x, f.y, f.rotation, f.mirror) for f in golden.flags)
    assert sorted((n.net, n.x, n.y) for n in assembled.page.labels) == sorted(
        (n.net, n.x, n.y) for n in golden.labels
    )


# --------------------------------------------------------------------------
# the assembly that actually runs: blocks on the spec's own grid
# --------------------------------------------------------------------------


def test_the_blocks_are_not_where_the_golden_had_them(spec):
    """Otherwise "assembly" would just be a re-encoding of the golden page."""
    moved = [
        block.id
        for block in spec.blocks
        if (block.at[0], block.at[1]) != block.template.origin_file
    ]
    assert len(moved) == 4, f"only {moved} moved; the spec is a transcription"


def test_the_spec_netlist_reproduces_the_golden(design, corrected_golden):
    """The double check (task 008a work item 5) — offline, before any draw."""
    report = compare_models(corrected_golden, design.model)
    assert report.is_empty, report.render()


def test_the_assembled_layout_lints_clean(design):
    plan, _frame = _plan(design)
    assert [v.render() for v in plan.violations] == []
    assert len(plan.placements) == 17
    assert len(plan.wires) >= 45  # the R5 junction split only ever adds runs


def test_the_assembled_content_fits_the_declared_sheet(design):
    """A layout that cannot fit its own page is not a layout."""
    extent = design.bbox_file()
    assert extent is not None
    x0, y0, x1, y1 = extent
    # Canvas space (task 010c): the sheet is y in [0, height], because file space
    # and the canvas are now the same y-up space. This assertion used to read
    # `y in [-height, 0]`, which was the mirrored frame the convention change
    # removed — and the spec's block positions moved with it.
    assert x0 >= 0 and x1 <= SHEET.x1
    assert y0 >= 0 and y1 <= SHEET.y1
    assert (x1 - x0) < SHEET.x1 - 2 * FRAME
    assert (y1 - y0) < SHEET.y1 - 2 * FRAME


def test_every_port_is_either_connected_or_reported(design):
    connected = {(block, role) for c in design.connections for block, role in c.ports}
    assert connected  # the CH340 spec connects everything
    for port in design.ports:
        assert (port.block, port.role) in connected, port
        assert port.local_net == port.page_net  # cut names match the spec's names
    assert design.notes == []


def test_the_nine_components_and_thirteen_nets_are_all_present(design):
    assert len(design.model.components) == 17
    assert set(design.model.nets) == {
        "GND", "+5V", "VCC", "D+", "D-", "RX", "TX",
        "NET1", "NET2", "NET3", "NET4", "NET5", "NET6",
    }
    assert design.model.components["C1"].value == "100nF"
    assert design.model.components["U3"].value == "2.2kΩ"
    assert design.model.components["R24"].lcsc_part == "C25905"
    assert design.model.components["R24"].props["expect_footprint"] == "R0402"


# --------------------------------------------------------------------------
# negative: a changed parameter must be a difference
# --------------------------------------------------------------------------


def test_changing_a_parameter_reports_a_difference(spec, corrected_golden):
    """Task 008a acceptance: "改一个参数值必须报差异"."""
    spec.params["usb.r24_value"] = "10K"
    try:
        changed = assemble(spec)
    finally:
        spec.params["usb.r24_value"] = "5.1K"

    assert changed.model.components["R24"].value == "10K"
    report = compare_models(corrected_golden, changed.model)
    assert not report.is_empty
    rows = [d for d in report.component_differences if "value differs" in d.detail]
    assert [d.subject for d in rows] == ["R24"], report.render()
    assert rows[0].golden == "5.1K" and rows[0].candidate == "10K"
    # and the difference is a *component* one: connectivity is untouched
    assert report.net_differences == [] and report.pin_differences == []


def test_the_changed_value_reaches_the_placement_step(spec):
    spec.params["core.c1_value"] = "1uF"
    try:
        changed = assemble(spec)
        plan, _frame = _plan(changed)
    finally:
        spec.params["core.c1_value"] = "100nF"
    step = next(p for p in plan.placements if p.designator == "C1")
    assert step.value == "1uF"


def test_an_unset_parameter_falls_back_to_the_template_default(spec):
    del spec.params["core.c3_value"]
    try:
        changed = assemble(spec)
    finally:
        spec.params["core.c3_value"] = "30pF"
    assert changed.model.components["C3"].value == "30pF"


# --------------------------------------------------------------------------
# negative: the three ways an assembly can be silently wrong
# --------------------------------------------------------------------------


def test_two_blocks_sharing_a_page_designator_are_refused(spec):
    """A clash is a clash however it arose — the derivation does not hide one.

    Two *different* templates that both claim `USB1` collide: they are not
    instances of one block, so neither gets an ordinal offset.
    """
    first, second = spec.blocks[0], spec.blocks[1]
    second.template.components[0].ref = first.template.components[0].ref
    with pytest.raises(AssemblyError, match="claimed twice"):
        assemble(spec)
    assert second.template_path != first.template_path


def test_two_instances_of_one_template_are_numbered_apart(spec):
    """008c item 6: the second instance of a template gets its own designators.

    A real second instance shares its rails with the first (that is what makes it
    the same block), so every connection that touches `usb` is extended to
    `usb_b`. Both instances then keep the same local net names *and* are joined,
    which is exactly the case the "two circuits with one name" refusal exists for.
    """
    from boardwise.core.blocks import BlockInstance, designator_map

    original = spec.blocks[0]
    second = BlockInstance(
        id="usb_b",
        template_path=original.template_path,
        template=original.template,
        at=(original.at[0] + 300.0, original.at[1]),
    )
    spec.blocks = list(spec.blocks) + [second]
    for connection in spec.connections:
        connection.ports = list(connection.ports) + [
            ("usb_b", role) for block, role in connection.ports if block == "usb"
        ]

    refs = designator_map(spec)
    assert refs["usb"] == {ref: ref for ref in refs["usb"]}
    assert refs["usb_b"]["USB1"] == "USB101"
    assert refs["usb_b"]["R24"] == "R124"

    design = assemble(spec)
    assert "USB1" in design.model.components
    assert "USB101" in design.model.components
    assert len([p for p in design.page.parts if p.designator.startswith("USB")]) == 2
    # The derivation is reported, not silent.
    assert any("placed 2 times" in note for note in design.notes)
    assert any("instance 1 of" in line and "USB1->USB101" in line for line in design.report)
    # Ordinal 0 keeps the template's own numbering: one instance per template is
    # exactly what 008a produced.
    assert design.model.components["USB1"].designator == "USB1"


def test_duplicate_block_ids_are_refused_rather_than_overwritten(spec):
    """Every helper here is keyed by block id, so a duplicate would shadow one."""
    spec.blocks = list(spec.blocks) + [spec.blocks[0]]
    with pytest.raises(BlockError, match="share the id"):
        assemble(spec)


def test_two_circuits_sharing_a_name_is_refused(spec):
    """Drop the D+ connection and both blocks still call their net D+."""
    original = spec.connections
    spec.connections = [c for c in original if c.net != "D+"]
    try:
        with pytest.raises(AssemblyError, match="same page net name"):
            assemble(spec)
    finally:
        spec.connections = original


def _one_block_spec(*, net_class: str, with_flag: bool, with_label: bool) -> BoardSpec:
    """A hand-minimal board: one block, one port, nothing else."""
    raw = {
        "kind": "boardwise-block-template",
        "version": SCHEMA_VERSION,
        "name": "tiny",
        "description": "",
        "provenance": {"kind": "textbook", "source": "hand", "designators": ["J1"], "note": ""},
        "origin_file": [0.0, 0.0],
        "bbox_file": [0.0, 0.0, 100.0, 100.0],
        "notes": [],
        "interface": [
            {"role": "P", "net": "P", "net_class": net_class, "position": [0.0, 0.0]}
        ],
        "params": [],
        "symbols": {
            "sym1": {
                "offsets": {"1": [0.0, 0.0]},
                "body": [0.0, -5.0, 10.0, 5.0],
                "pin_names": {"1": "a"},
            }
        },
        "components": [
            {
                "ref": "J1",
                "symbol": "sym1",
                "placement": {"x": 10.0, "y": 10.0, "rotation": 0.0, "mirror": False},
                "device": {"lcsc": "C1"},
                "footprint": "0402",
                "params": {},
                "pins": [{"number": "1", "name": "a", "net": "P"}],
            }
        ],
        "geometry": {
            "wires": [{"net": "P", "points": [[0.0, 0.0], [10.0, 0.0]]}],
            "flags": (
                [{"net": "P", "kind": "Ground", "x": 0.0, "y": 0.0, "rotation": 0.0,
                  "mirror": False, "symbol": "flag1"}]
                if with_flag
                else []
            ),
            "labels": (
                [{"net": "P", "x": 0.0, "y": 0.0, "rotation": 0.0}] if with_label else []
            ),
        },
    }
    template = template_from_json(raw)
    if with_flag:
        template.symbols["flag1"] = template.symbols["sym1"].__class__(
            uuid="flag1", offsets={}, body=(-10.0, 0.0, 0.0, 10.0), pin_names={}
        )
    return BoardSpec(
        name="tiny", description="", provenance_kind="textbook",
        provenance_source="hand", provenance_note="",
        blocks=[
            BlockInstance(
                id="only", template_path="<inline>", template=template, at=(0.0, 0.0)
            )
        ],
        connections=[], params={}, sheet_attrs={}, sheet_origin=(0.0, 0.0),
    )


def _geometry_less_spec(*nets: tuple[str, str]) -> BoardSpec:
    """A hand-minimal block with **no geometry at all** (2026-09-17 ruling).

    One component whose symbol carries each named net on its own pin, and
    nothing drawn: no wires, no flags, no labels. That is the shape a
    ``datasheet-extract`` / ``textbook`` block has, and the shape the assembler
    must name by synthesising anchors. ``nets`` is ``(net, net_class)`` per pin.
    """
    offsets: dict[str, list[float]] = {}
    pins: list[dict[str, str]] = []
    interface: list[dict[str, str]] = []
    for index, (net, net_class) in enumerate(nets, start=1):
        number = str(index)
        offsets[number] = [0.0, float(index) * 10.0]
        pins.append({"number": number, "name": net or "NC", "net": net})
        if not net:
            # An unconnected pin: real on the symbol, but not a net, so it has
            # no port and must never be named. `_resolve_nets` skips it.
            continue
        port: dict[str, str] = {"role": net, "net": net, "net_class": net_class}
        if net_class == "power":
            port["direction"] = "source"
            port["voltage"] = "3V3"
        elif net_class == "gnd":
            port["direction"] = "sink"
        interface.append(port)
    raw = {
        "kind": "boardwise-block-template",
        "version": SCHEMA_VERSION,
        "name": "authored",
        "description": "",
        "provenance": {"kind": "textbook", "source": "hand", "designators": ["U1"], "note": ""},
        "origin_file": [0.0, 0.0],
        "bbox_file": [0.0, 0.0, 0.0, 0.0],
        "notes": [],
        "interface": interface,
        "params": [],
        "symbols": {
            "sym1": {"offsets": offsets, "body": [-5.0, -5.0, 5.0, 40.0], "pin_names": {}}
        },
        "components": [
            {
                "ref": "U1",
                "symbol": "sym1",
                "placement": {"x": 100.0, "y": 0.0, "rotation": 0.0, "mirror": False},
                "device": {"lcsc": "C1"},
                "footprint": "0402",
                "params": {},
                "pins": pins,
            }
        ],
        "geometry": {"wires": [], "flags": [], "labels": []},
    }
    return BoardSpec(
        name="authored", description="", provenance_kind="textbook",
        provenance_source="hand", provenance_note="",
        blocks=[
            BlockInstance(
                id="author",
                template_path="<inline>",
                template=template_from_json(raw),
                at=(0.0, 0.0),
            )
        ],
        connections=[], params={}, sheet_attrs={}, sheet_origin=(0.0, 0.0),
    )


def test_a_geometry_less_block_gets_a_flag_on_every_rail_endpoint():
    """The ruling's forward case: synthesised anchors, one per pin endpoint.

    The three pins sit at block-local (100, 10), (100, 20) and (100, 30) in file
    space, one per net, so the page must end up with a flag on each rail: the
    power flag hangs **above** its endpoint (+y is up in file space) and the
    ground flag **below** it, each one cell (5.0) away, with a stub reaching
    back to the pin.
    """
    spec = _geometry_less_spec(("VCC", "power"), ("SIG", "signal"), ("GND", "gnd"))
    design = assemble(spec)

    flags = {(f.net, f.x, f.y) for f in design.page.flags}
    assert flags == {
        ("VCC", 100.0, 15.0),
        ("GND", 100.0, 25.0),
    }, flags
    # The signal net got a label at its own endpoint, not a flag.
    assert [(l.net, l.x, l.y) for l in design.page.labels] == [("SIG", 100.0, 20.0)]
    # Every flag hangs off a one-cell stub, and the stub reaches the pin.
    stubs = {(w.net, tuple(w.points)) for w in design.page.wires}
    assert stubs == {
        ("VCC", ((100.0, 10.0), (100.0, 15.0))),
        ("GND", ((100.0, 30.0), (100.0, 25.0))),
    }, stubs


def test_a_pin_with_no_net_is_not_given_an_anchor():
    """An unconnected pin must not be named, and must not name anyone.

    The empty net name is not a net: `_resolve_nets` skips exactly these pins
    when it collects the block's local nets, and `_block_pin_endpoints` has to
    agree, or a geometry-less block would get an anonymous flag/label on the
    page — a name nobody wrote and the editor cannot render. The connected nets
    on the same component must be unaffected.
    """
    spec = _geometry_less_spec(
        ("VCC", "power"), ("SIG", "signal"), ("GND", "gnd"), ("", "signal")
    )
    design = assemble(spec)

    # No anchor carries an empty name, in either flavour.
    assert [f for f in design.page.flags if not f.net] == []
    assert [l for l in design.page.labels if not l.net] == []
    assert [w for w in design.page.wires if not w.net] == []
    # The pin is not a net, so it added nothing at all.
    assert {(f.net, f.x, f.y) for f in design.page.flags} == {
        ("VCC", 100.0, 15.0),
        ("GND", 100.0, 25.0),
    }
    assert [(l.net, l.x, l.y) for l in design.page.labels] == [("SIG", 100.0, 20.0)]
    assert {(w.net, tuple(w.points)) for w in design.page.wires} == {
        ("VCC", ((100.0, 10.0), (100.0, 15.0))),
        ("GND", ((100.0, 30.0), (100.0, 25.0))),
    }


def test_the_synthesised_anchor_is_what_the_port_records():
    """The port's own anchor doubles as the flag it names (ruling item 4)."""
    spec = _geometry_less_spec(("VCC", "power"), ("SIG", "signal"), ("GND", "gnd"))
    design = assemble(spec)
    at = {(p.role, p.position) for p in design.ports}
    # VCC is power: topmost endpoint of its net (here its only one), one cell up.
    # GND is ground: bottommost endpoint, one cell down.
    # SIG is signal: no direction, so the leftmost (then lowest) endpoint.
    assert ("VCC", (100.0, 15.0)) in at, at
    assert ("GND", (100.0, 25.0)) in at, at
    assert ("SIG", (100.0, 20.0)) in at, at


def test_the_synthesised_anchors_are_deterministic():
    """Same input, byte-identical page — the whole point of a fixed rule."""
    spec = _geometry_less_spec(("VCC", "power"), ("SIG", "signal"), ("GND", "gnd"))
    first = assemble(spec)
    second = assemble(spec)
    assert first.page.flags == second.page.flags
    assert first.page.labels == second.page.labels
    assert [(w.group, w.net, w.points) for w in first.page.wires] == [
        (w.group, w.net, w.points) for w in second.page.wires
    ]
    assert first.ports == second.ports


def test_an_anchor_landing_inside_a_body_is_noted_not_refused():
    """The author's layout is signed; readability is a real-host question."""
    # The symbol body spans y in [-5, 40], so the GND flag one cell below the
    # pin at y=10 (i.e. y=5) is still inside it.
    spec = _geometry_less_spec(("GND", "gnd"))
    design = assemble(spec)
    assert any("falls inside" in note and "U1" in note for note in design.notes), design.notes


def test_a_geometry_less_block_may_not_declare_a_port_position():
    """`[0, 0]` is not "no position" — it is a claim nobody measured.

    Enforced by the **loader**, because that is where a template is checked: a
    writer that hand-sets `position` on an in-memory object has already skipped
    the gate, and catching that here would prove nothing about the file.
    """
    where = "authored-block"
    raw = {
        "kind": "boardwise-block-template",
        "version": SCHEMA_VERSION,
        "name": "authored",
        "description": "",
        "provenance": {"kind": "textbook", "source": "hand", "designators": ["U1"], "note": ""},
        "origin_file": [0.0, 0.0],
        "bbox_file": [0.0, 0.0, 0.0, 0.0],
        "notes": [],
        "interface": [
            {"role": "VCC", "net": "VCC", "net_class": "power", "position": [0.0, 0.0],
             "direction": "source", "voltage": "3V3"}
        ],
        "params": [],
        "symbols": {
            "sym1": {"offsets": {"1": [0.0, 0.0]}, "body": [-5.0, -5.0, 5.0, 5.0], "pin_names": {}}
        },
        "components": [
            {
                "ref": "U1", "symbol": "sym1",
                "placement": {"x": 100.0, "y": 0.0, "rotation": 0.0, "mirror": False},
                "device": {"lcsc": "C1"}, "footprint": "0402", "params": {},
                "pins": [{"number": "1", "name": "VCC", "net": "VCC"}],
            }
        ],
        "geometry": {"wires": [], "flags": [], "labels": []},
    }
    with pytest.raises(BlockError, match="no geometry"):
        template_from_json(raw, where=where)

    # And the mirror case: an empty geometry is what makes it forbidden, so
    # giving the same block one wire makes the position required again.
    raw["interface"][0].pop("position")
    raw["geometry"]["wires"] = [{"net": "VCC", "points": [[0.0, 0.0], [10.0, 0.0]]}]
    with pytest.raises(BlockError, match="carries geometry"):
        template_from_json(raw, where=where)


def test_a_power_port_that_carries_geometry_still_refuses_a_missing_flag():
    """The regression half of the split: the old refusal is untouched."""
    with pytest.raises(AssemblyError, match="to name it"):
        assemble(_one_block_spec(net_class="power", with_flag=False, with_label=False))


def test_the_refusal_no_longer_claims_a_flag_cannot_be_invented():
    """The falsified sentence is gone, not merely reworded.

    The old message argued a power port could not be named because "there is no
    way to invent a flag symbol". That was disproved (``sch.place_power`` takes
    no symbol uuid, and the replay degrades gracefully without one), so the
    replacement must not rest on it.
    """
    with pytest.raises(AssemblyError) as caught:
        assemble(_one_block_spec(net_class="power", with_flag=False, with_label=False))
    message = str(caught.value)
    assert "invent a flag symbol" not in message, message
    assert "carries geometry" in message, message


def test_a_power_port_with_no_flag_to_name_it_is_refused():
    """A template that carries geometry must name its own rail ports.

    This fixture has wires, so it takes the "replays the anchors its cut saw"
    path: its flags are a measurement, and a missing one is a defect in the
    template rather than something the assembler may synthesise a point for.
    (A geometry-less block *is* given synthesised anchors — see the tests below.)
    """
    with pytest.raises(AssemblyError, match="to name it"):
        assemble(_one_block_spec(net_class="power", with_flag=False, with_label=False))


def test_a_signal_port_with_no_anchor_gets_a_label_placed_for_it():
    """The assembly half of "at assembly, place a name at the port position"."""
    design = assemble(_one_block_spec(net_class="signal", with_flag=False, with_label=False))
    labels = [n for n in design.page.labels if n.net == "P" and (n.x, n.y) == (0.0, 0.0)]
    assert labels, "the port had no anchor and none was placed"
    assert any("placed a net label" in line for line in design.report)


def test_a_signal_port_that_already_has_an_anchor_gets_no_second_one():
    design = assemble(_one_block_spec(net_class="signal", with_flag=False, with_label=True))
    at_port = [n for n in design.page.labels if n.net == "P" and (n.x, n.y) == (0.0, 0.0)]
    assert len(at_port) == 1


def test_an_unknown_parameter_in_the_spec_is_refused(spec):
    spec.params["usb.nosuchparam"] = "1"
    try:
        with pytest.raises(BlockError, match="no parameter"):
            assemble(spec)
    finally:
        del spec.params["usb.nosuchparam"]


def test_a_renamed_net_moves_every_wire_and_pin_with_it(spec):
    """A connection may name a page net differently from the block's own name."""
    original = [c.net for c in spec.connections]
    for connection in spec.connections:
        if connection.net == "D+":
            connection.net = "USB_DP"
    try:
        design = assemble(spec)
    finally:
        for connection, name in zip(spec.connections, original):
            connection.net = name
    assert "USB_DP" in design.model.nets
    assert "D+" not in design.model.nets
    assert {m for m in design.model.nets["USB_DP"].pins} == {
        ("USB1", "6"), ("USB1", "8"), ("U1", "5"),
    }
    # the wires carried the old name; they must have been renamed too
    assert {w.net for w in design.page.wires} >= {"USB_DP", "D-"}
    renamed = [p for p in design.ports if p.page_net == "USB_DP"]
    assert {p.local_net for p in renamed} == {"D+"}
