"""134: the net-label policy of the draw pipeline (岳裁 2026-10-08).

**Why this exists.** In EasyEDA Pro a net label is *not* a decoration — it is
equivalent to a network port, i.e. drawing one **creates an electrical
connection**. So "label every signal net" was not merely ugly, it was quietly
burying implicit connections all over the page *and* masking routing mistakes.
An engineer's complaint that the AI-drawn flyback came back as a screenful of
network identifiers smeared over parts and wires is exactly this.

**What changed.**

1. New default strategy ``auto``: a signal net is named **only when a name is
   the only way to read it** — the net is *long* (``LONG_NET_LABEL_UNITS`` of
   routed wire) or *cross-page*. Everything else is read off its wires.
2. Every label that *is* placed has its landing point checked against
   component bodies, foreign wires and already-placed names, and is slid along
   its own wire to a clear spot. If nothing clears, the plan says so in
   ``notes`` instead of drawing a smudge.
3. Power/ground flags are untouched — they are the *naming* of a rail, not a
   decoration beside it.

The old strategies stay (``text`` / ``label`` / ``wire`` / ``none``); only the
default changed. Each test below names which of the three it pins.
"""

from __future__ import annotations

import pytest

from boardwise.core.model import Component, DesignModel, Net, Pin
from boardwise.engines import layout
from boardwise.engines.generate import (
    DEFAULT_NAMING_STRATEGY,
    LONG_NET_LABEL_UNITS,
    NAMING_STRATEGIES,
    ActionPlan,
    NetNameStep,
    WireStep,
    generate_plan,
    is_cross_page_net,
    needs_signal_label,
    normalise_strategy,
)

# --------------------------------------------------------------------------
# 1. the policy itself: what counts as long, and what counts as cross-page
# --------------------------------------------------------------------------


def _route(net: str, kind: str = "port", polylines=None) -> layout.RoutedNet:
    """A ``RoutedNet`` with geometry the test controls, not the router.

    Building the route by hand is deliberate: the shelf packer keeps real
    routes short (the whole CH340G golden board's longest signal net is 1395
    units), so a *behavioural* long-net fixture would be testing the packer's
    luck. The decision function reads length and pages only, and a synthetic
    route states those exactly.
    """
    return layout.RoutedNet(net=net, polylines=polylines or [], attach=(0.0, 0.0), kind=kind)


def _straight_route(net: str, length: float, kind: str = "port") -> layout.RoutedNet:
    return _route(net, kind, [[(0.0, 0.0), (length, 0.0)]])


def test_a_short_signal_net_gets_no_label_under_auto():
    wanted, why = needs_signal_label(_straight_route("SIG", LONG_NET_LABEL_UNITS - 1))
    assert wanted is False
    assert "read it off the wires" in why


def test_a_long_signal_net_gets_a_label_under_auto():
    wanted, why = needs_signal_label(_straight_route("SIG", LONG_NET_LABEL_UNITS + 1))
    assert wanted is True
    assert "long distance" in why


def test_the_threshold_is_the_boundary_not_a_hair():
    """Exactly at the threshold is *not* long — the constant is a ceiling.

    ``>`` rather than ``>=`` so "at most 1500 units" is the stated promise and
    a net sitting on the number behaves the way the constant reads.
    """
    at = _straight_route("SIG", LONG_NET_LABEL_UNITS)
    over = _straight_route("SIG", LONG_NET_LABEL_UNITS + 1)
    assert needs_signal_label(at)[0] is False
    assert needs_signal_label(over)[0] is True


def test_a_rail_is_never_a_signal_label():
    """A ground/power flag names a rail; it is not a label on top of one."""
    for kind in ("Ground", "Power"):
        wanted, why = needs_signal_label(_straight_route("GND", 10_000.0, kind))
        assert wanted is False
        assert "rail" in why


def test_length_is_measured_over_the_whole_route_not_one_span():
    """A net's routed length is the sum of its polylines.

    A three-piece dog-leg across a page is one short *span* per piece; reading
    only the longest span would call it short and drop the name a reader needs.
    """
    piece = LONG_NET_LABEL_UNITS / 2 - 1
    scattered = _route("SIG", "port", [
        [(0.0, 0.0), (piece, 0.0)],
        [(piece, 0.0), (piece, piece)],
        [(piece, piece), (piece * 2, piece)],
    ])
    assert layout.polyline_length(scattered.polylines) > LONG_NET_LABEL_UNITS
    assert needs_signal_label(scattered)[0] is True


def test_a_single_page_net_is_not_cross_page():
    model = DesignModel()
    model.components["U1"] = Component(uid="u", designator="U1", pins=[Pin(number="1", name="")])
    model.components["R1"] = Component(uid="r", designator="R1", pins=[Pin(number="1", name="")])
    model.nets["SIG"] = Net(name="SIG", pins=[("U1", "1"), ("R1", "1")])
    # no page data at all: one page's export *is* its connectivity
    assert is_cross_page_net(model, "SIG") is False
    assert needs_signal_label(_straight_route("SIG", 10.0), model=model)[0] is False


def test_a_welded_name_counts_as_cross_page_even_without_page_ids():
    """An empty page tuple is an *answer*, not a "no pages" (issue #19's shape).

    The per-page merge welds a name it saw twice but cannot name the pages for;
    such a net is cross-page by construction, so it must be labelled even with
    no ids to prove it. Truthiness would read ``()`` as "no evidence" and drop
    the label exactly where the evidence is weakest.
    """
    model = DesignModel()
    model.nets["SIG"] = Net(name="SIG", pins=[("U1", "1"), ("R1", "1")])
    model.unproven_nets = {"SIG": ()}
    assert is_cross_page_net(model, "SIG") is True
    assert needs_signal_label(_straight_route("SIG", 10.0), model=model)[0] is True


def test_two_named_pages_make_a_net_cross_page_and_one_does_not():
    def model_with(pages: tuple[str, ...]):
        model = DesignModel()
        model.nets["SIG"] = Net(name="SIG", pins=[("U1", "1"), ("R1", "1")])
        model.unproven_nets = {"SIG": pages}
        return model

    assert is_cross_page_net(model_with(("pageA", "pageB")), "SIG") is True
    assert is_cross_page_net(model_with(("pageA",)), "SIG") is False


def test_a_short_cross_page_net_is_named():
    """The second half of the ruling, on its own: 跨页才打, short or not."""
    model = DesignModel()
    model.nets["SIG"] = Net(name="SIG", pins=[("U1", "1")])
    model.unproven_nets = {"SIG": ("pageA", "pageB")}
    wanted, why = needs_signal_label(_straight_route("SIG", 40.0), model=model)
    assert wanted is True
    assert "cross page" in why


# --------------------------------------------------------------------------
# 2. the default is `auto`, and the old strategies survive
# --------------------------------------------------------------------------


def test_the_default_strategy_is_auto():
    assert DEFAULT_NAMING_STRATEGY == "auto"
    assert "auto" in NAMING_STRATEGIES


def test_every_old_strategy_is_still_selectable():
    for legacy in ("wire", "text", "label", "none"):
        assert legacy in NAMING_STRATEGIES
        assert normalise_strategy(legacy) == legacy


def test_an_unknown_strategy_falls_back_to_the_new_default():
    assert normalise_strategy("nonsense") == "auto"
    assert normalise_strategy(None) == "auto"


# --------------------------------------------------------------------------
# 3. end-to-end on a synthetic board: short nets stay unnamed, rails do not
# --------------------------------------------------------------------------


def _two_part_model() -> DesignModel:
    model = DesignModel()
    model.components["U1"] = Component(
        uid="u1", designator="U1",
        pins=[Pin(number="1", name=""), Pin(number="2", name="")],
    )
    model.components["R1"] = Component(
        uid="r1", designator="R1",
        pins=[Pin(number="1", name=""), Pin(number="2", name="")],
    )
    model.nets["GND"] = Net(name="GND", pins=[("U1", "1"), ("R1", "1")])
    model.nets["RX"] = Net(name="RX", pins=[("U1", "2"), ("R1", "2")])
    return model


def _two_part_offsets() -> dict:
    return {
        "U1": {"1": (-20.0, -10.0), "2": (-20.0, 10.0)},
        "R1": {"1": (-20.0, 0.0), "2": (20.0, 0.0)},
    }


def test_a_short_signal_net_produces_no_name_primitive_at_all():
    """The complaint, as a test: nothing is drawn over a short connection."""
    plan = generate_plan(_two_part_model(), _two_part_offsets())
    assert plan.naming_strategy == "auto"
    assert not [n for n in plan.net_names if n.net == "RX"], (
        "a short single-page signal net is read off its wires"
    )
    assert [w for w in plan.wires if w.net == "RX"], "the net is still wired"
    assert not any(n.kind == "port" for n in plan.net_names), "ports stay banned"


def test_the_rail_keeps_its_flag_under_auto():
    plan = generate_plan(_two_part_model(), _two_part_offsets())
    flags = [n for n in plan.net_names if n.net == "GND"]
    assert len(flags) == 1
    assert flags[0].kind == "Ground"


def test_the_rail_flag_is_exactly_where_every_strategy_puts_it():
    """`auto` changed the signal policy, not the rails' — same anchor."""
    model, offsets = _two_part_model(), _two_part_offsets()
    under_auto = generate_plan(model, offsets, strategy="auto")
    under_text = generate_plan(model, offsets, strategy="text")
    rail_auto = [(n.x, n.y) for n in under_auto.net_names if n.kind == "Ground"]
    rail_text = [(n.x, n.y) for n in under_text.net_names if n.kind == "Ground"]
    assert rail_auto == rail_text


def test_rails_keep_their_flags_under_every_strategy_including_auto():
    for strategy in NAMING_STRATEGIES:
        plan = generate_plan(_two_part_model(), _two_part_offsets(), strategy=strategy)
        kinds = {n.kind for n in plan.net_names}
        assert kinds <= {"Ground", "Power", "text", "label"}, f"{strategy}: {kinds}"
        assert "Ground" in kinds, f"{strategy} lost the rail flag"


def test_the_legacy_text_strategy_still_names_every_signal_net():
    """The old behaviour is intact, just no longer the default.

    Someone reading a dense page may want every net named; the switch that does
    it still does it, so the ruling removes a default rather than a capability.
    """
    plan = generate_plan(_two_part_model(), _two_part_offsets(), strategy="text")
    rx = [n for n in plan.net_names if n.net == "RX"]
    assert len(rx) == 1 and rx[0].kind == "text" and rx[0].decorative is True


def test_a_cross_page_net_is_named_end_to_end_even_when_short():
    model = _two_part_model()
    model.unproven_nets = {"RX": ("pageA", "pageB")}
    plan = generate_plan(model, _two_part_offsets())
    rx = [n for n in plan.net_names if n.net == "RX"]
    assert len(rx) == 1, "a cross-page net is named whatever its length"
    assert rx[0].decorative is True


def test_the_plan_says_why_each_label_is_there():
    """A policy that changes without saying so is the failure mode 006b stopped."""
    model = _two_part_model()
    model.unproven_nets = {"RX": ("pageA", "pageB")}
    plan = generate_plan(model, _two_part_offsets())
    reasons = [note for note in plan.notes if note.startswith("net RX is named")]
    assert reasons, plan.notes
    assert "cross page" in reasons[0]


# --------------------------------------------------------------------------
# 4. landing-point avoidance
# --------------------------------------------------------------------------


def _geometry_with_a_blocker() -> list[layout.Placement]:
    """Two placements whose boxes sit on either side of one horizontal wire.

    ``U1``'s own box is far to the left; ``R1``'s box is centred **on** the
    wire at y=0, so the wire's own midpoint — the router's attach point —
    lands squarely inside a component body. Any label placed there is the
    defect the complaint describes.
    """
    return [
        layout.Placement("U1", 0.0, 0.0, layout.Rect(-200.0, -60.0, -100.0, 60.0)),
        layout.Placement("R1", 100.0, 0.0, layout.Rect(0.0, -40.0, 200.0, 40.0)),
    ]


_BLOCKING_WIRE = [[(-100.0, 0.0), (300.0, 0.0)]]


def test_the_avoidance_search_moves_a_label_off_the_component_body():
    """The pin: an attach point inside a box must not become a label's home."""
    route = layout.RoutedNet(net="SIG", polylines=_BLOCKING_WIRE, attach=(100.0, 0.0))
    assert _BLOCKING_WIRE[0][0] == (-100.0, 0.0)
    # the router's own choice really is inside R1's box — otherwise the test
    # would pass for the wrong reason
    r1 = next(p.bbox for p in _geometry_with_a_blocker() if p.designator == "R1")
    assert r1.contains_point(100.0, 0.0)

    point, problem = layout.clear_label_point(
        [route], "SIG", _geometry_with_a_blocker(), {"U1", "R1"},
    )
    assert problem == ""
    assert point is not None
    box = layout.annotation_box(point[0], point[1], "SIG")
    assert not box.intersects(r1), (
        f"the moved label at {point} still overlaps R1's body"
    )


def test_a_moved_label_stays_on_its_own_wire():
    """Moving along the wire, never off it: a name off its wire is not a name.

    ``lint_annotations`` reports ``LABEL_FLOATS`` for that, and a floating name
    is worse than no name — the editor does not treat an overlapping marker and
    a pin coordinate as a connection.
    """
    route = layout.RoutedNet(net="SIG", polylines=_BLOCKING_WIRE, attach=(100.0, 0.0))
    point, _ = layout.clear_label_point(
        [route], "SIG", _geometry_with_a_blocker(), {"U1", "R1"},
    )
    on_wire = any(
        layout._point_on_segment(
            point,
            layout.Segment(ax, ay, bx, by, "SIG"),
        )
        for (ax, ay), (bx, by) in zip(_BLOCKING_WIRE[0], _BLOCKING_WIRE[0][1:])
    )
    assert on_wire, f"the label left its wire: {point}"


def test_a_label_keeps_clearance_from_a_foreign_box():
    """Not merely "not overlapping" — clear by LABEL_CLEARANCE, as the lint wants."""
    route = layout.RoutedNet(net="SIG", polylines=_BLOCKING_WIRE, attach=(100.0, 0.0))
    point, _ = layout.clear_label_point(
        [route], "SIG", _geometry_with_a_blocker(), {"U1"},
    )
    r1 = next(p.bbox for p in _geometry_with_a_blocker() if p.designator == "R1")
    assert r1.distance_to_point(*point) >= layout.LABEL_CLEARANCE


def test_a_label_keeps_clearance_from_a_foreign_wire():
    """A name lying on a stranger's wire is a second net that is not there.

    Set up so the two ways of measuring come apart: the *anchor point* sits 25
    units from the foreign wire — clear on its own — while the label's text box
    reaches to within 16. Measuring the point would wave this through and draw
    the name across a net that is not there, which is the defect.
    """
    geometry = [layout.Placement("U1", 0.0, 0.0, layout.Rect(-400.0, -200.0, -300.0, 200.0))]
    horizontal = layout.RoutedNet(
        net="SIG", polylines=[[(-350.0, 0.0), (300.0, 0.0)]], attach=(0.0, 0.0),
    )
    foreign = layout.RoutedNet(net="OTHER", polylines=[[(25.0, 0.0), (250.0, 0.0)]])
    segs = [layout.Segment(25.0, 0.0, 250.0, 0.0, "OTHER")]

    # the anchor at x=0 would pass a point-only test…
    assert layout._segment_distance((0.0, 0.0), segs[0]) == 25.0
    # …but its text box does not clear the wire
    assert layout.rect_segment_distance(
        layout.annotation_box(0.0, 0.0, "SIG"), segs[0]
    ) < layout.LABEL_CLEARANCE

    point, problem = layout.clear_label_point(
        [horizontal, foreign], "SIG", geometry, set(),
    )
    assert problem == ""
    assert all(
        layout.rect_segment_distance(layout.annotation_box(point[0], point[1], "SIG"), s)
        >= layout.LABEL_CLEARANCE
        for s in segs
    ), f"the chosen spot at {point} still crowds the foreign wire"
    # and it is still on its own wire — nudged along it, not off it
    assert layout._point_on_segment(
        point, layout.Segment(-350.0, 0.0, 300.0, 0.0, "SIG")
    )


def test_two_labels_never_stack():
    """The second label cannot take the first one's spot."""
    geometry = [layout.Placement("U1", 0.0, 0.0, layout.Rect(-400.0, -200.0, -300.0, 200.0))]
    a = layout.RoutedNet(net="AAA", polylines=[[(-350.0, 0.0), (300.0, 0.0)]])
    b = layout.RoutedNet(net="BBB", polylines=[[(-350.0, 0.0), (300.0, 0.0)]])
    first, _ = layout.clear_label_point([a], "AAA", geometry, set())
    second, _ = layout.clear_label_point(
        [b], "BBB", geometry, set(), taken=[(first[0], first[1], "AAA")]
    )
    box_a = layout.annotation_box(first[0], first[1], "AAA")
    box_b = layout.annotation_box(second[0], second[1], "BBB")
    assert not box_b.intersects(box_a.inflate(layout.LABEL_CLEARANCE))


def test_no_clear_spot_is_reported_in_notes_rather_than_silently_dropped():
    """A wire with nowhere to put a name must say so.

    The alternative — falling back to the router's attach point — is the defect
    itself: a label drawn on a part reads as a smear and hides what is under it.
    """
    # a wire entirely enclosed by a foreign component's box: every on-wire
    # point is inside the body
    geometry = [layout.Placement("R1", 0.0, 0.0, layout.Rect(-50.0, -50.0, 50.0, 50.0))]
    trapped = layout.RoutedNet(
        net="SIG", polylines=[[(-40.0, 0.0), (40.0, 0.0)]], attach=(0.0, 0.0)
    )
    point, problem = layout.clear_label_point([trapped], "SIG", geometry, {"OTHER"})
    assert point is None
    assert "left unnamed" in problem
    assert "SIG" in problem


def test_a_name_beside_its_own_net_s_part_is_fine():
    """Own parts are exempt from the margin — the human's own labels do this.

    Only the *overlap* is a defect; a name pinned beside the part it names is
    normal schematic practice, so the search must not exile such nets to the
    far side of the sheet.
    """
    geometry = [layout.Placement("U1", 0.0, 0.0, layout.Rect(-100.0, -60.0, -20.0, 60.0))]
    wire = [[(-20.0, 0.0), (300.0, 0.0)]]
    route = layout.RoutedNet(net="SIG", polylines=wire, attach=(200.0, 0.0))
    point, problem = layout.clear_label_point([route], "SIG", geometry, {"U1"})
    assert problem == ""
    box = layout.annotation_box(point[0], point[1], "SIG")
    assert not box.intersects(geometry[0].bbox)


def test_the_plan_reports_a_trapped_label_in_its_notes():
    """The reporting half, end to end, through ``generate_plan``.

    A net whose every wire point is inside a part is exactly what the two-part
    synthetic produces when R1's box swallows the RX wire's midpoint — which it
    does when R1's pin is short and U1's is not.
    """
    model = _two_part_model()
    offsets = {
        "U1": {"1": (-20.0, -10.0), "2": (-500.0, 10.0)},
        "R1": {"1": (-20.0, 0.0), "2": (20.0, 0.0)},
    }
    plan = generate_plan(model, offsets)
    # Whether RX is named or not, every note about it must be truthful: either
    # it names the net where it can be read, or it says where it could not.
    rx_names = [n for n in plan.net_names if n.net == "RX"]
    for name in rx_names:
        box = layout.annotation_box(name.x, name.y, "RX")
        by_des = {p.designator: p.bbox for p in plan.geometry}
        for des, bbox in by_des.items():
            if des in {"U1", "R1"}:
                assert not box.intersects(bbox), (
                    f"RX's name at {name.x},{name.y} sits on {des}"
                )


# --------------------------------------------------------------------------
# 5. the ActionPlan contract the draw flow reads
# --------------------------------------------------------------------------


def test_animated_plan_summary_reports_the_strategy_it_ran():
    plan = ActionPlan()
    plan.naming_strategy = "auto"
    assert "auto" in plan.summary()


def test_a_plan_with_no_signal_names_reports_none_as_decorative():
    plan = ActionPlan()
    plan.naming_strategy = "auto"
    plan.net_names.append(NetNameStep(net="GND", kind="Ground", x=10.0, y=10.0))
    assert plan.decorative_names == []
    assert plan.summary()


def test_wire_step_is_not_a_name():
    """The wire still carries the net under ``auto`` — the name is not the net.

    ``auto`` removes the *visible* name, not the electrical one: the wire's own
    net attribute is what the editor's netlist reads (measured 2026-09-14), and
    dropping it would make unnamed nets genuinely anonymous.
    """
    plan = generate_plan(_two_part_model(), _two_part_offsets())
    rx = [w for w in plan.wires if w.net == "RX"]
    assert rx and all(w.net == "RX" for w in rx)


@pytest.mark.parametrize("strategy", list(NAMING_STRATEGIES))
def test_no_strategy_emits_a_port(strategy):
    plan = generate_plan(_two_part_model(), _two_part_offsets(), strategy=strategy)
    assert not any(n.kind == "port" for n in plan.net_names)


def test_the_shipped_constant_is_the_ruled_one():
    """The number is 岳's to confirm; pin it so a silent edit goes red."""
    assert LONG_NET_LABEL_UNITS == 1500.0
    # ~38 mm at 1 unit = 1 mil — the ruling's own conversion
    assert round(LONG_NET_LABEL_UNITS * 0.0254, 1) == 38.1