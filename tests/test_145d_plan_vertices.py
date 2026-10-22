"""145d: the two plan defects 145c's landing measured — pinned as behaviour.

145c put 145a's own drawing on the live page and apply refused it for two reasons
that were neither C13 nor the read-back (145c sec.5.3):

* **`live: Q1.1 is on net '' with nothing among this plan's pins, but the plan says
  ['Q1.1']`** — `GATE` is a single-pin net: one pin, one label, and **no wire of the
  net anywhere**. `module_plan` wrote a downgrade saying the name is carried on the
  wire (`sch.place_wire` net=…) while drawing no wire at all, so the editor's netlist
  held neither the name nor the pin (`netlist_after_apply.json`: `GATE` zero times).
  A net that has a name and no conductor gets 057 sec.4's **stub** on a single-module
  plan too;
* **`canvas: net SEC_12V: no wire vertex at (280, 760)`** — the flag's lead
  `(280,760) → (280,785)` lay *on top of* the trunk it hangs off. The host merges
  collinear wires (pit 32), so `(280,760)` was no vertex of the page at all, while
  the flag's own anchor `(280,785)` — measured, `P1_geometry_after_apply.json` — was.
  A run another wire of the net already covers is not drawn, and the wire a flag
  attaches *inside* of is cut at that point, so every wire end the plan states is a
  vertex the page keeps.

Both are asserted twice: on the plan's own shape, and against
`drawapply._wire_problems` / `drawapply._live_problems` — apply's own checkers, on a
page written the way the host reports one (the checker is not re-implemented here).
"""

from __future__ import annotations

import pytest

from boardwise.core.circuitspec import CircuitSpec
from boardwise.core.layoutplan import (
    LayoutLabel,
    LayoutPart,
    LayoutPlan,
    LayoutPowerSymbol,
    LayoutSegment,
    LayoutSource,
)
from boardwise.core.presentationspec import PresentationSpec
from boardwise.core.symbolprofile import SymbolPin, SymbolPose, SymbolProfile
from boardwise.engines import drawapply

PROV = "engineer_confirmed"
HASH = "a" * 64


def _resistor() -> SymbolProfile:
    return SymbolProfile(
        symbol_ref="R0402",
        title="test resistor",
        body=(-5.0, -5.0, 5.0, 5.0),
        poses=[SymbolPose(rotation=0, mirror=False)],
        pins=[
            SymbolPin(number="1", tip=(-15.0, 0.0), direction="left"),
            SymbolPin(number="2", tip=(15.0, 0.0), direction="right"),
        ],
    )


def _flag(ref: str) -> SymbolProfile:
    """A pin-less profile: that is how the compiler reads "this is a flag"."""
    return SymbolProfile(
        symbol_ref=ref,
        title="test rail flag",
        body=(-6.0, 0.0, 6.0, 18.0),
        poses=[SymbolPose(rotation=0, mirror=False)],
        pins=[],
    )


def _presentation() -> PresentationSpec:
    return PresentationSpec.from_dict({
        "kind": "boardwise-presentation-spec", "specVersion": 1,
        "grammarRef": "ic-periphery",
        "sidePreferences": {"input": "left", "output": "right",
                            "power": "top", "gnd": "bottom"},
    })


def _circuit(nets) -> CircuitSpec:
    return CircuitSpec.from_dict({
        "kind": "boardwise-circuit-spec", "specVersion": 1,
        "parts": [
            {"id": "R1", "symbolRef": "R0402", "value": "10k",
             "lcsc": "C25744", "provenance": PROV},
            {"id": "D3", "symbolRef": "R0402", "value": "SS310",
             "lcsc": "C9900021858", "provenance": PROV},
        ],
        "nets": list(nets),
    })


def _part(part_id: str, x: float = 0.0, y: float = 0.0) -> LayoutPart:
    return LayoutPart(
        part_id=part_id, symbol_ref="R0402",
        symbol_hash=_resistor().geometry_hash(), x=x, y=y,
    )


def _load(layout, circuit, profiles) -> object:
    return drawapply.module_plan(
        layout, circuit, _presentation(), profiles,
        lcsc_by_part={"R1": "C25744", "D3": "C9900021858"},
        keep_names=True,
    )


def _wires(plan, net: str):
    return [wire for wire in plan.change.draw_wires if wire.net == net]


def _endpoint_pairs(plan):
    return [
        (wire.net, (round(wire.points[0][0], 6), round(wire.points[0][1], 6)))
        for wire in plan.change.draw_wires
    ] + [
        (wire.net, (round(wire.points[-1][0], 6), round(wire.points[-1][1], 6)))
        for wire in plan.change.draw_wires
    ]


def _page(*, wires, netflags=(), designators=(("R1", 0.0, 0.0),)) -> dict:
    """A `sch.geometry` dump the way the host reports one (036's own shape)."""
    return {
        "components": [
            {"primitiveId": f"p-{name}",
             "state": {"Designator": name, "X": x, "Y": y, "ComponentType": "part",
                       "Rotation": 0, "Mirror": False}}
            for name, x, y in designators
        ],
        "wires": [
            {"primitiveId": f"w-{index}",
             "state": {"Line": [c for point in points for c in point], "Net": net}}
            for index, (net, points) in enumerate(wires)
        ],
        "netlabels": [],
        "meta": {"available": {"components": True, "wires": True}},
    }


# ===================== 1. a named net with no conductor gets a real stub


@pytest.fixture()
def bare_plan():
    """`GATE` exact shape: one pin, one label on it, and no wire of that net."""
    layout = LayoutPlan(
        source=LayoutSource(circuit_sha256=HASH, presentation_sha256=HASH),
        parts=[_part("R1")],
        segments=[],
        labels=[LayoutLabel(
            net="GATE", text="GATE", bbox=(-55.0, -4.5, -23.0, 4.5),
            x=-15.0, y=0.0, part_id="R1",
        )],
    )
    circuit = _circuit([{"id": "GATE", "class": "signal", "members": ["R1.1"],
                         "provenance": PROV}])
    return _load(layout, circuit, {"R0402": _resistor()})


def test_a_named_net_without_a_conductor_is_given_a_stub_wire(bare_plan) -> None:
    wires = _wires(bare_plan, "GATE")
    assert len(wires) == 1, [wire.points for wire in wires]
    wire = wires[0]
    assert wire.points[0] == (-15.0, 0.0), "the stub must start on the pin's own tip"
    assert wire.points == [(-15.0, 0.0), (-25.0, 0.0)], (
        "057 sec.4: 2 lattice steps out of the anchor, towards the label's box"
    )
    assert wire.from_pin == "R1.1", "the read-back has to know which end is a pin"
    assert "name stub" in wire.purpose


def test_the_stub_carries_the_name_so_the_netlist_leg_can_be_satisfied(bare_plan) -> None:
    """The 145c failure, replayed: `R1.1` was on `''` with nothing beside it."""
    live_without = {("R1", "1"): ""}
    assert drawapply._live_problems(bare_plan, live_without) == [
        "R1.1 is on net '' with nothing among this plan's pins, "
        "but the plan says ['R1.1']"
    ], "the shape 145c measured, reproduced for the same plan without the stub"
    live_with = {("R1", "1"): "GATE"}
    assert drawapply._live_problems(bare_plan, live_with) == []


def test_the_stub_is_a_wire_that_is_placed_with_its_own_net_name(bare_plan) -> None:
    """`sch.place_wire` net=… is what makes the name land (029-b, 069 sec.9)."""
    assert "GATE" not in drawapply.unnamed_nets(bare_plan), (
        "a net named by a flag is placed unnamed; this one has no flag, so the "
        "name must go on the wire"
    )
    text = " ".join(
        line for line in bare_plan.change.draw_downgrades if "net GATE" in line
    )
    assert "a 10-unit stub (-15, 0) → (-25, 0) carries the name instead" in text, text


def test_the_downgrade_does_not_promise_a_wire_the_plan_does_not_draw(bare_plan) -> None:
    """145c's defect in one sentence: the old text said "named on the wire itself"."""
    text = " ".join(line for line in bare_plan.change.draw_downgrades if "net GATE" in line)
    assert "the net is named on the wire itself instead" not in text
    assert "carries the name instead" in text


def test_a_net_that_keeps_a_conductor_is_untouched() -> None:
    """The other branch, byte for byte: 145d must not change a wired net's label."""
    layout = LayoutPlan(
        source=LayoutSource(circuit_sha256=HASH, presentation_sha256=HASH),
        parts=[_part("R1")],
        segments=[LayoutSegment(net="TAP", points=[(-15.0, 0.0), (-60.0, 0.0)])],
        labels=[LayoutLabel(
            net="TAP", text="TAP", bbox=(-55.0, -4.5, -23.0, 4.5),
            x=-15.0, y=0.0, part_id="R1",
        )],
    )
    circuit = _circuit([{"id": "TAP", "class": "signal", "members": ["R1.1"],
                         "provenance": PROV}])
    plan = _load(layout, circuit, {"R0402": _resistor()})
    assert len(_wires(plan, "TAP")) == 1, "no stub is added over a wire that is there"
    text = " ".join(line for line in plan.change.draw_downgrades if "net TAP" in line)
    assert "a planned wire of TAP runs through that point" in text


# ===================== 2. a flag's hang point is a real vertex


def _hgv_plan(*, lead) -> object:
    """The SEC_12V shape: a rail, and a flag the compiler reached with a lead."""
    profile = _flag("PWR-SEC_12V")
    layout = LayoutPlan(
        source=LayoutSource(circuit_sha256=HASH, presentation_sha256=HASH),
        parts=[_part("D3", 300.0, 790.0)],
        segments=[
            LayoutSegment(net="SEC_12V", points=[(280.0, 790.0), (280.0, 710.0),
                                                 (715.0, 710.0)]),
        ] + ([LayoutSegment(net="SEC_12V", points=list(lead))] if lead else []),
        power_symbols=[LayoutPowerSymbol(
            symbol_ref="PWR-SEC_12V", symbol_hash=profile.geometry_hash(),
            net="SEC_12V", x=280.0, y=785.0, rotation=0.0,
        )],
    )
    circuit = _circuit([{"id": "SEC_12V", "class": "power", "members": ["D3.1"],
                         "provenance": PROV}])
    return _load(layout, circuit, {"R0402": _resistor(), "PWR-SEC_12V": profile})


def test_a_run_another_wire_of_the_net_covers_is_not_drawn() -> None:
    plan = _hgv_plan(lead=[(280.0, 760.0), (280.0, 785.0)])
    assert [
        wire.points for wire in _wires(plan, "SEC_12V")
    ] == [
        [(280.0, 790.0), (280.0, 785.0)],
        [(280.0, 785.0), (280.0, 710.0), (715.0, 710.0)],
    ], "the lead is gone and the rail is cut at the point the flag attaches to"
    assert not any(
        (280.0, 760.0) in (wire.points[0], wire.points[-1])
        for wire in plan.change.draw_wires
    ), "no wire may claim the transparent point 145c's page did not hold"


def test_the_cut_pieces_are_one_net_and_connected() -> None:
    plan = _hgv_plan(lead=[(280.0, 760.0), (280.0, 785.0)])
    pieces = _wires(plan, "SEC_12V")
    assert {wire.net for wire in pieces} == {"SEC_12V"}
    joined = pieces[0].points[-1]
    assert joined in pieces[1].points, "the two pieces share the cut point"


def test_the_plan_says_why_it_dropped_the_run_and_cut_the_wire() -> None:
    plan = _hgv_plan(lead=[(280.0, 760.0), (280.0, 785.0)])
    text = " ".join(plan.change.draw_downgrades)
    assert "already covered by another wire of the same net" in text
    assert "is cut at (280, 785)-(280, 785)" in text


def test_the_canvas_leg_passes_on_a_page_that_holds_the_flag_s_node() -> None:
    """Measured: the merged rail lists (280,785) — the flag attaches there."""
    plan = _hgv_plan(lead=[(280.0, 760.0), (280.0, 785.0)])
    page = _page(wires=[("", [(280.0, 790.0), (280.0, 785.0), (280.0, 710.0),
                              (715.0, 710.0)])],
                 designators=(("D3", 300.0, 790.0),))
    assert drawapply._wire_problems(plan, page) == []


def test_the_cut_is_load_bearing_a_page_without_that_node_is_caught() -> None:
    """The mutation this rule exists for: no node where the flag attaches."""
    plan = _hgv_plan(lead=[(280.0, 760.0), (280.0, 785.0)])
    page = _page(wires=[("", [(280.0, 790.0), (280.0, 710.0), (715.0, 710.0)])],
                 designators=(("D3", 300.0, 790.0),))
    problems = drawapply._wire_problems(plan, page)
    assert problems, "a page without the flag's node must be caught"
    assert set(problems) == {
        "net SEC_12V: no wire vertex at (280, 785) on the page, "
        "but the plan draws a wire reaching it"
    }, problems


def test_a_perpendicular_lead_is_kept_and_its_branch_point_is_cut_into_being() -> None:
    """The HVDC shape (145c measured (135,695) as a real node on the page)."""
    profile = _flag("PWR-HVDC")
    layout = LayoutPlan(
        source=LayoutSource(circuit_sha256=HASH, presentation_sha256=HASH),
        parts=[_part("D3", 300.0, 790.0)],
        segments=[
            LayoutSegment(net="HVDC", points=[(160.0, 690.0), (160.0, 695.0),
                                              (85.0, 695.0)]),
            LayoutSegment(net="HVDC", points=[(135.0, 695.0), (135.0, 705.0)]),
        ],
        power_symbols=[LayoutPowerSymbol(
            symbol_ref="PWR-HVDC", symbol_hash=profile.geometry_hash(),
            net="HVDC", x=135.0, y=705.0, rotation=0.0,
        )],
    )
    circuit = _circuit([{"id": "HVDC", "class": "power", "members": ["D3.1"],
                         "provenance": PROV}])
    plan = _load(layout, circuit, {"R0402": _resistor(), "PWR-HVDC": profile})
    wires = [wire.points for wire in _wires(plan, "HVDC")]
    assert [(135.0, 695.0), (135.0, 705.0)] in wires, (
        "a lead that leaves the rail at a right angle draws a conductor: it stays"
    )
    assert [(160.0, 690.0), (160.0, 695.0), (135.0, 695.0)] in wires
    assert [(135.0, 695.0), (85.0, 695.0)] in wires, (
        "the branch point is a vertex of the plan, not a point inside a run"
    )


def test_a_flag_that_anchors_on_a_wire_end_gets_no_extra_wire() -> None:
    """The family question: only a flag *inside* a run needs a cut."""
    profile = _flag("PWR-SEC_12V")
    layout = LayoutPlan(
        source=LayoutSource(circuit_sha256=HASH, presentation_sha256=HASH),
        parts=[_part("D3", 300.0, 790.0)],
        segments=[
            LayoutSegment(net="SEC_12V", points=[(280.0, 790.0), (280.0, 710.0)]),
        ],
        power_symbols=[LayoutPowerSymbol(
            symbol_ref="PWR-SEC_12V", symbol_hash=profile.geometry_hash(),
            net="SEC_12V", x=280.0, y=710.0, rotation=0.0,
        )],
    )
    circuit = _circuit([{"id": "SEC_12V", "class": "power", "members": ["D3.1"],
                         "provenance": PROV}])
    plan = _load(layout, circuit, {"R0402": _resistor(), "PWR-SEC_12V": profile})
    assert [wire.points for wire in _wires(plan, "SEC_12V")] == [
        [(280.0, 790.0), (280.0, 710.0)]
    ]


def test_two_identical_runs_drop_the_copy_never_both() -> None:
    """A paired rule: dropping both would take the net's only conductor with them."""
    layout = LayoutPlan(
        source=LayoutSource(circuit_sha256=HASH, presentation_sha256=HASH),
        parts=[_part("R1")],
        segments=[
            LayoutSegment(net="TAP", points=[(-15.0, 0.0), (-60.0, 0.0)]),
            LayoutSegment(net="TAP", points=[(-15.0, 0.0), (-60.0, 0.0)]),
        ],
    )
    circuit = _circuit([{"id": "TAP", "class": "signal", "members": ["R1.1"],
                         "provenance": PROV}])
    plan = _load(layout, circuit, {"R0402": _resistor()})
    assert [wire.points for wire in _wires(plan, "TAP")] == [
        [(-15.0, 0.0), (-60.0, 0.0)]
    ]

# ===================== 3. every pin of a conductor-less net gets its own stub


def _four_pin_layout(*, segments) -> LayoutPlan:
    """Two resistors, four pins tip-to-tip, one label on each pin.

    520E's measured single-module shape: a `direct-wire` obligation the router
    cannot satisfy is downgraded to "one name per pin", so the net reaches
    `module_plan` with **no conductor of its own** and four labels — one on each
    pin. The boxes sit on the side each pin points at, the way the compiler puts
    them.
    """
    return LayoutPlan(
        source=LayoutSource(circuit_sha256=HASH, presentation_sha256=HASH),
        parts=[_part("R1", 0.0, 0.0), _part("D3", 200.0, 0.0)],
        segments=list(segments),
        labels=[
            #: R1.1 → (-15, 0), text to the left
            LayoutLabel(net="RAIL", text="RAIL", bbox=(-45.0, -4.5, -23.0, 4.5),
                        x=-15.0, y=0.0, part_id="R1"),
            #: R1.2 → (15, 0), text to the right
            LayoutLabel(net="RAIL", text="RAIL", bbox=(23.0, -4.5, 45.0, 4.5),
                        x=15.0, y=0.0, part_id="R1"),
            #: D3.1 → (185, 0), text to the left
            LayoutLabel(net="RAIL", text="RAIL", bbox=(155.0, -4.5, 177.0, 4.5),
                        x=185.0, y=0.0, part_id="D3"),
            #: D3.2 → (215, 0), text to the right
            LayoutLabel(net="RAIL", text="RAIL", bbox=(223.0, -4.5, 245.0, 4.5),
                        x=215.0, y=0.0, part_id="D3"),
        ],
    )


_RAIL_MEMBERS = ["R1.1", "R1.2", "D3.1", "D3.2"]


def _four_pin_plan(*, segments):
    circuit = _circuit([{"id": "RAIL", "class": "signal",
                         "members": _RAIL_MEMBERS, "provenance": PROV}])
    return _load(_four_pin_layout(segments=segments), circuit,
                 {"R0402": _resistor()})


@pytest.fixture()
def four_pin_bare_plan():
    """No conductor of RAIL anywhere in the plan, four pins, four labels."""
    return _four_pin_plan(segments=[])


def test_every_pin_of_a_conductor_less_net_gets_its_own_stub(four_pin_bare_plan) -> None:
    """520f, the defect: four pins, and only the **first** one was named.

    145d asked "does this net have no conductor?" and read `built.wires` — the
    very list the loop appends each stub to. The first label therefore flipped
    the answer for the other three: one stub, and three pins left on an unnamed
    net with nothing drawn on the canvas (520E's own measurement, and a broken
    netlist for every pin but one).
    """
    wires = _wires(four_pin_bare_plan, "RAIL")
    assert len(wires) == 4, [
        (wire.from_pin, wire.points) for wire in wires
    ]
    assert all("name stub" in wire.purpose for wire in wires), [
        wire.purpose for wire in wires
    ]
    assert [wire.from_pin for wire in wires] == _RAIL_MEMBERS, (
        "one stub per pin, each starting on that pin's own tip — not four copies "
        "of the first pin's stub"
    )
    assert [wire.points[0] for wire in wires] == [
        (-15.0, 0.0), (15.0, 0.0), (185.0, 0.0), (215.0, 0.0)
    ]


def test_each_stub_is_recorded_and_carries_the_name_on_its_own_wire(
    four_pin_bare_plan,
) -> None:
    """The book-keeping half: one downgrade per stub, and no stub left unnamed.

    A stub that is drawn without its `downgrades` line is 145c's silent
    substitution; a stub whose net the plan reports as unnamed is a wire the
    editor's netlist will not name (029-b). Both are cheap to say and cheap to
    break, so both are said.
    """
    lines = [
        line for line in four_pin_bare_plan.change.draw_downgrades
        if "net RAIL" in line
    ]
    assert len(lines) == 4, lines
    assert all("carries the name instead" in line for line in lines), lines
    assert "RAIL" not in drawapply.unnamed_nets(four_pin_bare_plan)


def test_a_conductor_less_net_with_one_pin_still_gets_exactly_one_stub() -> None:
    """The paired rule at the other end: 145d's own GATE shape must not double.

    A snapshot that said "no conductor" too *eagerly* would draw a second stub
    over the first, and the plan's own answer to "which pin is this net on"
    would stop being one wire per pin. The second assertion is the book-keeping
    half of the same rule: a label that was stubbed takes the stub branch and
    nothing else, so it must not also be reported as an anchor the plan left
    alone ("other planned wire(s) of GATE carry the name" would be a lie about a
    net that has none — 145c's defect, one branch lower).
    """
    layout = LayoutPlan(
        source=LayoutSource(circuit_sha256=HASH, presentation_sha256=HASH),
        parts=[_part("R1")],
        segments=[],
        labels=[LayoutLabel(
            net="GATE", text="GATE", bbox=(-55.0, -4.5, -23.0, 4.5),
            x=-15.0, y=0.0, part_id="R1",
        )],
    )
    circuit = _circuit([{"id": "GATE", "class": "signal", "members": ["R1.1"],
                         "provenance": PROV}])
    plan = _load(layout, circuit, {"R0402": _resistor()})
    assert [wire.points for wire in _wires(plan, "GATE")] == [
        [(-15.0, 0.0), (-25.0, 0.0)]
    ]
    lines = [line for line in plan.change.draw_downgrades if "net GATE" in line]
    assert len(lines) == 1, lines
    assert "carries the name instead" in lines[0], lines
    assert "other planned wire(s)" not in lines[0], lines


def test_a_net_that_keeps_a_conductor_keeps_the_behaviour_it_had() -> None:
    """145d's sentence on the shape 520f touches: four labels, one planned run.

    The run reaches R1's two pins and stops; D3's two labels sit off it. The net
    has a conductor, so it is not `bare` — and 520f leaves it exactly as it was:
    the run is drawn, nothing is stubbed over it, the two carried anchors say the
    name is on that wire, and the two the run does not reach keep 145d's own
    sentence about other planned wires carrying the name. Both halves are
    asserted, because a snapshot read too *eagerly* would stub the two D3 labels
    (that is the mutation this test is for) while one read not eagerly enough
    would stub the whole net four times.
    """
    plan = _four_pin_plan(
        segments=[LayoutSegment(net="RAIL", points=[(-15.0, 0.0), (15.0, 0.0)])]
    )
    assert [wire.points for wire in _wires(plan, "RAIL")] == [
        [(-15.0, 0.0), (15.0, 0.0)]
    ], "the plan's own run, and nothing stubbed over it"
    text = " ".join(
        line for line in plan.change.draw_downgrades if "net RAIL" in line
    )
    assert "carries the name instead" not in text, text
    assert text.count("a planned wire of RAIL runs through that point") == 2, text
    assert text.count("other planned wire(s) of RAIL carry the name") == 2, text
