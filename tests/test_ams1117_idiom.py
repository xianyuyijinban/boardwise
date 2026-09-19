"""The hand-drawn LDO block (task 010): geometry a human can read.

`power_ams1117_3v3` was this project's first *authored* block — a
`datasheet-extract` with no wires at all, whose page the assembler named by
synthesising one anchor per pin endpoint. The 2026-09-18 real-host smoke showed
the ceiling of that path: a page with no wire on it, a flag on every pin, and
six texts stacked on U1's left edge. Electricity was right (the netlist matched
pin for pin) and the drawing was not.

The block therefore carries geometry drawn by hand now, and what such a block
has to support are a *drawing*'s claims: every run is where the layout says it
is, no run crosses a symbol body, no two nets touch, every run ends on a
terminal, each rail is named exactly once, and the pin the package already
connects internally (SOT-223 pin 2 / tab) is left off the page.

There is no golden to compare an authored block against, so these tests hold it
to its own declared facts — its symbol offsets, its bodies, its placements.
That is what makes them able to fail, and the mutation tests at the bottom
prove it in the two ways that matter: one pin moved onto the wrong net, and one
run re-drawn through a body.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from boardwise.core.blocks import (
    BlockInstance,
    BlockTemplate,
    BoardSpec,
    load_block_template,
    load_board_spec,
    template_from_json,
)
from boardwise.core.geometry import transform_point
from boardwise.engines.assemble import assemble
from boardwise.engines.layout import Rect, Segment

ROOT = Path(__file__).resolve().parents[1]
BLOCK = ROOT / "blocklib" / "blocks" / "power_ams1117_3v3.json"
SPEC = ROOT / "blocklib" / "specs" / "ams1117_smoke.json"

Point = tuple[float, float]

#: The drawing as data, in file order. A change to the block's geometry has to
#: be a change to this list as well, which is the point of writing it out: the
#: routing ruling is a human decision, so it is pinned rather than derived.
RULED_RUNS: tuple[tuple[str, tuple[Point, ...]], ...] = (
    # Task 010c §5: the two rail legs aim at the *true* pin tips. The regulator's
    # symbol offsets were recorded mirrored (pin 1 GND was at y=-10 when it is at
    # +10 on the canvas), so before the convention fix +5V was wired to the pad
    # that is actually GND and the ground leg to the pad that is VIN. The
    # electrical netlist was unaffected — which is exactly why it went unnoticed.
    ("+5V", ((75.0, 90.0), (50.0, 90.0), (50.0, 130.0))),
    ("+5V", ((50.0, 130.0), (25.0, 130.0))),
    ("VCC", ((165.0, 100.0), (180.0, 100.0), (180.0, 130.0))),
    ("VCC", ((180.0, 130.0), (215.0, 130.0))),
    ("VCC", ((215.0, 130.0), (240.0, 130.0))),
    ("GND", ((75.0, 110.0), (60.0, 110.0), (60.0, 65.0))),
    ("GND", ((60.0, 65.0), (25.0, 65.0))),
    ("GND", ((25.0, 65.0), (25.0, 90.0))),
    ("GND", ((60.0, 65.0), (215.0, 65.0))),
    ("GND", ((215.0, 65.0), (215.0, 90.0))),
)

#: The page netlist the layout has to reproduce: the regulator's tab on VCC,
#: its input on +5V, its ground on GND, and both capacitors across the pair.
RULED_NETLIST: dict[str, list[str]] = {
    "+5V": ["C1.2", "U1.3"],
    "VCC": ["C2.2", "U1.4"],
    "GND": ["C1.1", "C2.1", "U1.1"],
}


@pytest.fixture(scope="module")
def template():
    return load_block_template(BLOCK)


@pytest.fixture(scope="module")
def design():
    return assemble(load_board_spec(SPEC))


def _pin_tip(template, ref: str, number: str) -> Point:
    """A pin tip in block-local **file** space, through the one convention.

    `core.geometry.transform_point` is what the parsers, the assembler and the
    replay all rotate with, so a pin's position here is the position the draw
    chain will place — not a second opinion about it.
    """
    component = next(c for c in template.components if c.ref == ref)
    ox, oy = template.symbols[component.symbol].offsets[number]
    return transform_point(
        ox,
        oy,
        rotation=component.rotation,
        mirror=component.mirror,
        ox=component.x,
        oy=component.y,
    )


def _body_box(template, ref: str) -> Rect:
    """The part's drawn extent in block-local file space, rotation applied."""
    component = next(c for c in template.components if c.ref == ref)
    x0, y0, x1, y1 = template.symbols[component.symbol].body
    corners = [(x0, y0), (x0, y1), (x1, y0), (x1, y1)]
    xs: list[float] = []
    ys: list[float] = []
    for cx, cy in corners:
        px, py = transform_point(
            cx,
            cy,
            rotation=component.rotation,
            mirror=component.mirror,
            ox=component.x,
            oy=component.y,
        )
        xs.append(px)
        ys.append(py)
    return Rect(min(xs), min(ys), max(xs), max(ys))


def _runs(template) -> list[tuple[str, tuple[Point, ...]]]:
    return [(wire.net, tuple(wire.points)) for wire in template.wires]


def _netlist(design) -> dict[str, list[str]]:
    return {
        name: sorted(f"{des}.{number}" for des, number in net.pins)
        for name, net in design.model.nets.items()
    }


def _segments(template):
    for wire in template.wires:
        for a, b in zip(wire.points, wire.points[1:]):
            yield wire.net, a, b


# --------------------------------------------------------------------------
# the layout, as the ruling states it
# --------------------------------------------------------------------------


def test_the_parts_sit_where_the_layout_puts_them(template):
    """U1 unrotated in the middle; both capacitors upright at 90.

    `90` is the ruling's own number, and `test_pin_2_is_the_upper_pad...` below
    is why it works: under the project's rotation convention (counter-clockwise
    in the canvas's y-up frame, as task 010c measured and restored) 90 puts the
    capacitor's pin 2 on top. The block briefly carried 270 — a workaround for
    the mirrored frame 010c removed — and that is void now.
    """
    assert {
        component.ref: (
            component.x,
            component.y,
            component.rotation,
            component.mirror,
        )
        for component in template.components
    } == {
        "U1": (120.0, 100.0, 0.0, False),
        "C1": (25.0, 110.0, 90.0, False),
        "C2": (215.0, 110.0, 90.0, False),
    }


def test_pin_2_is_the_upper_pad_under_the_one_rotation_convention(template):
    """The angle is not cosmetic: it decides which pad is on the rail.

    `transform_point` rotates **counter-clockwise in the canvas's y-up frame**
    (task 010c: the 2026-09-13 calibration concluded clockwise, correctly but in
    the mirrored frame the pipeline used then — see `core/geometry.py`), so at 90
    the capacitor's pin 2 comes out on top and at 270 pin 1 does. The layout puts
    pin 2 on the rail, which is what the pin/net table and the assembled netlist
    both say — and 270 is asserted here as the *other* answer, so a future reader
    cannot quietly flip one of the two and call it noise.
    """
    assert _pin_tip(template, "C1", "2") == (25.0, 130.0)
    assert _pin_tip(template, "C1", "1") == (25.0, 90.0)
    assert _pin_tip(template, "C2", "2") == (215.0, 130.0)
    assert _pin_tip(template, "C2", "1") == (215.0, 90.0)

    component = next(c for c in template.components if c.ref == "C1")
    ox, oy = template.symbols[component.symbol].offsets["2"]
    assert transform_point(
        ox, oy, rotation=270.0, mirror=False, ox=component.x, oy=component.y
    ) == (25.0, 90.0)
    assert transform_point(
        ox, oy, rotation=90.0, mirror=False, ox=component.x, oy=component.y
    ) == (25.0, 130.0)


def test_every_pin_tip_lands_on_the_ruled_coordinate(template):
    """The tips the routing is drawn against, regulator side included.

    The regulator's y values are task 010c §5's truth table: pin 1 GND is the
    **upper-left** pad (+10) and pin 3 VIN the lower one (-10). The block carried
    them mirrored until the convention fix — the block note's claim that the
    offsets had already been negated into a y-up space was written about a frame
    that was not y up.
    """
    assert {
        (ref, number): _pin_tip(template, ref, number)
        for ref, number in (
            ("U1", "1"),
            ("U1", "2"),
            ("U1", "3"),
            ("U1", "4"),
            ("C1", "1"),
            ("C1", "2"),
            ("C2", "1"),
            ("C2", "2"),
        )
    } == {
        ("U1", "1"): (75.0, 110.0),
        ("U1", "2"): (75.0, 100.0),
        ("U1", "3"): (75.0, 90.0),
        ("U1", "4"): (165.0, 100.0),
        ("C1", "1"): (25.0, 90.0),
        ("C1", "2"): (25.0, 130.0),
        ("C2", "1"): (215.0, 90.0),
        ("C2", "2"): (215.0, 130.0),
    }


def test_the_runs_are_the_ruled_geometry(template):
    assert _runs(template) == list(RULED_RUNS)


def test_every_run_is_orthogonal_and_has_at_most_one_bend(template):
    """The routing discipline: straight legs, no diagonal, few corners.

    A three-point run has one corner; a two-point run is a single leg. Nothing
    here is allowed a second bend, because a second bend is what turns a rail
    into a detour a reader has to trace.
    """
    for net, points in _runs(template):
        assert len(points) <= 3, f"{net}: {points} has more than one bend"
        for (ax, ay), (bx, by) in zip(points, points[1:]):
            assert ax == bx or ay == by, f"{net}: ({ax},{ay})-({bx},{by}) is diagonal"
            assert (ax, ay) != (bx, by), f"{net}: zero-length leg at ({ax},{ay})"


# --------------------------------------------------------------------------
# the drawing is legal: nothing crosses a body, nothing crosses another net
# --------------------------------------------------------------------------


def test_the_body_boxes_are_the_ones_the_routing_was_checked_against(template):
    """Named explicitly, so the crossing test cannot pass on a wrong box.

    These four boxes are what "no wire through a part" means here; they come
    from the block's own symbol bodies rotated by the placement, and a mistake
    in either would otherwise show up as a *passing* test with the wires
    somewhere else entirely.
    """
    assert {ref: _body_box(template, ref) for ref in ("U1", "C1", "C2")} == {
        "U1": Rect(85.0, 85.0, 155.0, 115.0),
        "C1": Rect(17.0, 100.0, 33.0, 120.0),
        "C2": Rect(207.0, 100.0, 223.0, 120.0),
    }


@pytest.mark.parametrize("ref", ["U1", "C1", "C2"])
def test_no_run_crosses_a_symbol_body(template, ref):
    """Every leg against every body, with the real ruler.

    The predicate is the layout validator's own (`layout._segment_crosses_rect`,
    interior-only) rather than a re-implementation: generation and checking
    have to agree about what "crosses" means or the check measures a different
    board than the one that gets drawn.

    What this test does *not* reuse is the validator's `WIRE_THROUGH_BOX`
    *escape*: `validate_full` excuses a segment that carries a pin tip of the
    same part at one end, so a run drawn from U1's own pin straight into U1's
    body passes the page lint (measured on mutation 2 below: the page lints to
    two `ENDPOINT_NOT_TERMINAL` rows and no `WIRE_THROUGH_BOX` at all). A
    block's own drawing is held to the geometric rule here, without the escape.
    """
    from boardwise.engines import layout

    box = _body_box(template, ref)
    crossed = [
        f"{net} ({ax:g},{ay:g})-({bx:g},{by:g})"
        for net, (ax, ay), (bx, by) in _segments(template)
        if layout._segment_crosses_rect(Segment(ax, ay, bx, by, net), box)
    ]
    assert crossed == [], f"runs crossing {ref}: {crossed}"


def test_the_crossing_ruler_fires_when_a_run_does_enter_a_body(template):
    """Positive control for the test above — otherwise "clear" means nothing.

    A wire drawn *into* the regulator from its input pin is the mistake the
    layout is written to avoid, and the ruler has to call it a crossing; a wire
    that merely ends on the body's edge stays legal, which is what lets a pin
    lead touch its own part.
    """
    from boardwise.engines import layout

    box = _body_box(template, "U1")
    through = Segment(75.0, 110.0, 155.0, 110.0, "+5V")
    assert layout._segment_crosses_rect(through, box)
    touching = Segment(75.0, 100.0, 85.0, 100.0, "VCC")
    assert not layout._segment_crosses_rect(touching, box)


def test_every_run_end_is_a_terminal(template):
    """A run may end on a pin, on another run of its own net, or on a name.

    Nothing else: a leg that just stops is a stub the reader has to guess
    about, and the draw chain's own terminality check would have to accept it
    for the page to lint clean.
    """
    tips = {
        _pin_tip(template, c.ref, p["number"])
        for c in template.components
        for p in c.pins
        if p["net"]
    }
    ends: Counter[Point] = Counter()
    for _net, points in _runs(template):
        for point in (points[0], points[-1]):
            ends[point] += 1
    names = {(flag.x, flag.y) for flag in template.flags}

    dangling = [
        f"({x:g},{y:g})"
        for (x, y) in ends
        if (x, y) not in tips and ends[(x, y)] < 2 and (x, y) not in names
    ]
    assert dangling == [], f"run ends that terminate nothing: {dangling}"


def test_no_endpoint_of_one_net_lands_on_another_nets_run(template):
    """The shape the editor turns into a junction dot, i.e. a short."""
    from boardwise.engines import layout

    shorts: list[str] = []
    for net, (ax, ay), (bx, by) in _segments(template):
        seg = Segment(ax, ay, bx, by, net)
        for other_net, points in _runs(template):
            if other_net == net:
                continue
            for point in (points[0], points[-1]):
                if layout._point_on_segment(point, seg):
                    shorts.append(f"{other_net} end {point} on {net} {seg.points()}")
    assert shorts == [], f"cross-net touches: {shorts}"


@pytest.mark.parametrize(
    "ref,number",
    [
        ("U1", "1"),
        ("U1", "3"),
        ("U1", "4"),
        ("C1", "1"),
        ("C1", "2"),
        ("C2", "1"),
        ("C2", "2"),
    ],
)
def test_a_connected_pin_is_a_run_endpoint_and_never_mid_run(template, ref, number):
    """A pin lands on a run's *end*, not in the middle of one.

    Measured 2026-09-15 (`engines/replay.py::split_at_junctions`): the editor
    merges runs that share an endpoint and repeats the junction point there,
    and the shape whose netlist came back with the pin unconnected was a pin
    inside a single run. The rail trunks are therefore written as two runs that
    meet at the capacitor's pin tip rather than as one run through it.
    """
    from boardwise.engines import layout

    tip = _pin_tip(template, ref, number)
    endpoints = [
        point
        for _net, points in _runs(template)
        for point in (points[0], points[-1])
    ]
    assert tip in endpoints, f"{ref}.{number} at {tip} is not an end of any run"

    mid_run = [
        f"{net} {Segment(ax, ay, bx, by, net).points()}"
        for net, (ax, ay), (bx, by) in _segments(template)
        if layout._point_on_segment(tip, Segment(ax, ay, bx, by, net))
        and tip not in ((ax, ay), (bx, by))
    ]
    assert mid_run == [], f"{ref}.{number} lands inside a run: {mid_run}"


# --------------------------------------------------------------------------
# names: one flag per rail, and the port is that flag
# --------------------------------------------------------------------------


def test_exactly_one_flag_per_net(design):
    """The whole repair in one line: eight per-pin flags became three rails."""
    assert Counter(flag.net for flag in design.page.flags) == {
        "+5V": 1,
        "VCC": 1,
        "GND": 1,
    }
    assert {flag.net: flag.kind for flag in design.page.flags} == {
        "+5V": "Power",
        "VCC": "Power",
        "GND": "Ground",
    }


def test_every_flag_sits_on_one_of_its_own_nets_runs(template):
    """A flag off its wire is not merely ugly: the editor does not connect it."""
    from boardwise.engines import layout

    floating = [
        f"{flag.net} at ({flag.x:g},{flag.y:g})"
        for flag in template.flags
        if not any(
            layout._point_on_segment((flag.x, flag.y), Segment(ax, ay, bx, by, net))
            for net, (ax, ay), (bx, by) in _segments(template)
            if net == flag.net
        )
    ]
    assert floating == [], f"flags floating off their net: {floating}"


def test_the_ports_are_the_flag_anchors_and_nothing_is_synthesised(design, template):
    """The two-path rule, exercised from the other side.

    A block with geometry replays the anchors it carries: each port's position
    is one of its own flags, the assembler adds no stub and no label, and the
    report says nothing about synthesised anchors. The flag count is asserted
    against the *template's* flags for the same reason — a synthesised anchor
    would show up as extra flags here even though the file has three.
    """
    annotations = {(flag.x, flag.y): flag.net for flag in design.page.flags}
    # Page positions are block-local + the spec's `at` in **canvas** space (task
    # 010c). The spec moved with the convention — its old (400, -300) put the
    # block below the sheet origin — so these three are local + (400, 300).
    assert {port.role: (port.position, port.page_net) for port in design.ports} == {
        "+5V": ((425.0, 430.0), "+5V"),
        "VCC": ((640.0, 430.0), "VCC"),
        "GND": ((510.0, 365.0), "GND"),
    }
    for port in design.ports:
        assert annotations.get(port.position) == port.page_net

    assert design.page.labels == []
    assert len(design.page.flags) == len(template.flags) == 3
    assert len(design.page.wires) == len(template.wires) == 10
    assert [line for line in design.report if "synthesised" in line] == []
    assert [note for note in design.notes if "synthesised" in note] == []


# --------------------------------------------------------------------------
# electricity: the netlist the layout has to reproduce
# --------------------------------------------------------------------------


def test_the_assembled_netlist_is_the_ruled_one(design):
    assert _netlist(design) == {name: sorted(pins) for name, pins in RULED_NETLIST.items()}


def test_pin_2_is_left_off_the_page(design):
    """SOT-223's pin 2 and its tab are one piece of metal.

    The tab (pin 4) is on VCC, so pin 2 is already connected inside the package
    and is not drawn to anything: it carries no net, it is a member of no net,
    and no wire, flag or label is drawn at its tip.
    """
    pins = {pin.number: pin for pin in design.model.components["U1"].pins}
    assert pins["2"].name == "VOUT"
    assert pins["2"].net is None
    assert not any(("U1", "2") in net.pins for net in design.model.nets.values())

    # The page position of that tip (block-local (75, 100) moved by the spec's
    # (400, -300)): nothing is drawn there, and no run even passes over it —
    # an anchor there would be a name for a pin that has none.
    tip = (475.0, -200.0)
    assert tip not in [
        point for wire in design.page.wires for point in wire.points
    ]
    assert tip not in [(flag.x, flag.y) for flag in design.page.flags]
    assert tip not in [(label.x, label.y) for label in design.page.labels]


# --------------------------------------------------------------------------
# mutations: the two rulers above go red on a real defect
# --------------------------------------------------------------------------


def _mutated_template(mutate) -> BlockTemplate:
    """The committed block, re-read with one edit applied in memory.

    Read from disk every time rather than copied from the module fixture: a
    mutant must be a mutation of what is *committed*, and mutating the shared
    fixture would leak into every other test in the file.
    """
    raw = json.loads(BLOCK.read_text(encoding="utf-8"))
    mutate(raw)
    return template_from_json(raw, where="<mutant>")


def _assemble_mutant(template):
    return assemble(
        BoardSpec(
            name="mutant",
            description="",
            provenance_kind="datasheet-extract",
            provenance_source="hand",
            provenance_note="",
            blocks=[
                BlockInstance(
                    id="pwr",
                    template_path="<mutant>",
                    template=template,
                    at=(400.0, -300.0),
                )
            ],
            connections=[],
            params={},
            sheet_attrs={},
            sheet_origin=(0.0, 0.0),
        )
    )


def test_a_pin_on_the_wrong_net_is_caught_by_the_netlist_assertion():
    """Mutation 1: C2's ground pad moved onto VCC (i.e. the mount flipped).

    The routing is untouched, so the drawing still looks right; what changes is
    which net the wire it lands on belongs to. That is precisely the failure a
    per-segment coordinate test cannot see and the netlist test must.
    """

    def flip(raw):
        for component in raw["components"]:
            if component["ref"] == "C2":
                for pin in component["pins"]:
                    if pin["number"] == "1":
                        pin["net"] = "VCC"

    mutated = _assemble_mutant(_mutated_template(flip))
    assert _netlist(mutated) != RULED_NETLIST
    assert _netlist(mutated)["VCC"] == ["C2.1", "C2.2", "U1.4"]
    assert _netlist(mutated)["GND"] == ["C1.1", "U1.1"]


def test_a_run_through_a_body_is_caught_by_the_crossing_ruler():
    """Mutation 2: the +5V leg drawn east into the regulator instead of west.

    The netlist is unaffected (the run still starts on pin 3), so only a
    geometric check can refuse this page — which is what
    `test_no_run_crosses_a_symbol_body` is for.
    """
    from boardwise.engines import layout

    def detour(raw):
        raw["geometry"]["wires"][0]["points"] = [[75.0, 110.0], [155.0, 110.0]]

    mutated = _mutated_template(detour)
    assert _runs(mutated)[0] == ("+5V", ((75.0, 110.0), (155.0, 110.0)))

    box = _body_box(mutated, "U1")
    crossed = [
        (net, (ax, ay), (bx, by))
        for net, (ax, ay), (bx, by) in _segments(mutated)
        if layout._segment_crosses_rect(Segment(ax, ay, bx, by, net), box)
    ]
    assert crossed == [("+5V", (75.0, 110.0), (155.0, 110.0))]

    # ... and the netlist is untouched by the same mutation, so the two tests
    # are genuinely checking two different things. Measured against the
    # unmutated block rather than against RULED_NETLIST, so this test stays
    # about the geometric ruler and cannot go red for an electrical reason.
    untouched = _mutated_template(lambda raw: None)
    assert _netlist(_assemble_mutant(mutated)) == _netlist(_assemble_mutant(untouched))
