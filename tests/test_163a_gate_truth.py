"""163a: the draw gate's rulers — the five holes the E-series closed.

The subject is *which* geometry the gate measures. Every test here is written
against the failure the corresponding hole let through, not against the shape of
the code:

* **E1** — the solver judged the page against the A4 calibration constants even
  when the caller had measured a different sheet, and the replay fallback threw
  the measured frame away. A non-A4 page therefore reported clean.
* **E2** — the page-selection pass measured the *router's* attach points while
  the finished plan draws other ones; two rulers for constraint 5.
* **E3** — nothing in the terminal check looked at a name's box against a
  **foreign wire**; only the label-avoidance search did, so a rail flag anchored
  at the router's own point could be drawn across a stranger's wire with the
  gate reporting clean.
* **E5** — a netlist pin the plan could not place was a *note*: the gate could
  not see it, so ``draw`` would execute a page that carries less connectivity
  than the netlist it reproduces.
* **E6** — two nets' wires on the same line are a short, and were filed under the
  advisory spacing code, i.e. drawn anyway.
* **E7** — ``net_exits`` decided a corner pin's exit side as "first of W, E, N,
  S", while the router decides it by whichever stub run stays clear of the
  sibling tips; the demand a gap is sized from was not the demand the router
  makes.

E4 (the solver's flag boxes) is **not** here: see the counter-evidence in
``outputs/163a/evidence.md`` — the solver places flags with ``sch.place_power``
and holds no symbol body to measure a glyph from, so the only box it can pass is
the one :func:`boardwise.engines.layout.annotation_box` already predicts for a
glyph-less anchor (``boardwise.engines.assemble`` states the same contract).
"""

from __future__ import annotations

import pytest

from boardwise.core.model import Component, DesignModel, Net, Pin
from boardwise.engines import generate, layout, replay
from boardwise.parsers.schematic import PageLayout, PlacedPart


# --------------------------------------------------------------------------
# E1 — the measured frame reaches the solver, and the fallback says which
# --------------------------------------------------------------------------


def _one_tall_part_net():
    """A single part whose box is 140 units tall, on a one-net board."""
    model = DesignModel(
        components={
            "U1": Component(uid="u", designator="U1", pins=[
                Pin(number="1", name="1", net="N1"),
                Pin(number="2", name="2", net="N1"),
            ]),
        },
        nets={"N1": Net(name="N1", pins=[("U1", "1"), ("U1", "2")])},
    )
    offsets = {"U1": {"1": (0.0, 0.0), "2": (0.0, 100.0)}}
    return model, offsets


#: A small sheet, measured. ``FRAME`` insets it, and the packing's origin is
#: above the A4 title block's band (140), so a 140-tall box lands at y 140..280 —
#: inside A4's 826 and well outside this page's 200.
SMALL_FRAME = layout.Rect(10.0, 10.0, 290.0, 190.0)


def test_a_page_measured_smaller_than_a4_reports_the_boxes_that_leave_it():
    """E1: the solver must be able to judge the page the caller measured."""
    model, offsets = _one_tall_part_net()

    a4 = generate.generate_plan(model, offsets)
    assert "OUT_OF_SHEET" not in {v.code for v in a4.violations}, (
        "precondition: on the A4 default this board fits"
    )

    small = generate.generate_plan(model, offsets, frame=SMALL_FRAME)
    codes = {v.code for v in small.violations}
    assert "OUT_OF_SHEET" in codes, sorted(codes)


def test_the_replay_fallback_hands_the_measured_frame_to_the_solver():
    """E1: a measured frame is the whole point of the fallback path."""
    model, offsets = _one_tall_part_net()
    frame = replay.SheetFrame(
        bbox=layout.Rect(0.0, 0.0, 300.0, 200.0),
        drawable=SMALL_FRAME,
        title_block=layout.Rect(120.0, 10.0, 290.0, 58.0),
    )

    no_page, source = replay.replay_or_solver(model, None, frame, offsets)
    assert source == "generic solver"
    assert "OUT_OF_SHEET" in {v.code for v in no_page.violations}, [v.render() for v in no_page.violations]
    assert any("against the measured frame" in note for note in no_page.notes), no_page.notes

    # and with no frame at all the A4 default stands, said out loud
    unframed, _source = replay.replay_or_solver(model, None, None, offsets)
    assert "OUT_OF_SHEET" not in {v.code for v in unframed.violations}
    assert not any("measured frame" in note for note in unframed.notes), unframed.notes

    # a golden page without a measured frame: the replay refuses and the solver
    # says which one it therefore used
    page = PageLayout(parts=[PlacedPart("U1", 0.0, 0.0, 0.0, False)])
    from_page, _source = replay.replay_or_solver(model, page, None, offsets)
    assert any("no measured sheet frame" in note for note in from_page.notes), from_page.notes


def test_a_measured_title_block_is_the_ruler_the_naming_search_avoids():
    """E1's other half: the title-block keep-out moves with the frame."""
    model, offsets = _one_tall_part_net()
    # A title block over the whole page: nothing can be placed off it, and the
    # measured rectangle — not the A4 constant — is what the plan is held to.
    whole_page_title = layout.Rect(10.0, 10.0, 290.0, 190.0)
    plan = generate.generate_plan(
        model, offsets, frame=layout.Rect(0.0, 0.0, 300.0, 200.0),
        title_block=whole_page_title,
    )
    assert "PLACEMENT_ON_TITLE_BLOCK" in {v.code for v in plan.violations}, [
        v.render() for v in plan.violations
    ]


# --------------------------------------------------------------------------
# E2 — one ruler for constraint 5 on the solver path
# --------------------------------------------------------------------------


def _one_net_board():
    model = DesignModel(
        components={
            "U1": Component(uid="u", designator="U1", pins=[
                Pin(number="1", name="1", net="A"),
            ]),
        },
        nets={"A": Net(name="A", pins=[("U1", "1")])},
    )
    offsets = {"U1": {"1": (0.0, 0.0)}}
    return model, offsets


def test_validate_full_measures_the_named_anchors_and_only_those():
    """E2: the attach fallback is a fallback, not a second live ruler."""
    model, _offsets = _one_net_board()
    routes = [
        layout.RoutedNet(
            net="A", polylines=[[(0.0, 0.0), (100.0, 0.0)]],
            attach=(100.0, 0.0), kind="port",
        )
    ]
    pins = {("U1", "1"): (0.0, 0.0)}
    # a foreign part whose box starts 15 units past the wire's end
    near = [layout.Placement("R9", 0.0, 0.0, layout.Rect(115.0, -10.0, 155.0, 10.0))]

    legacy = layout.validate_full(model, near, routes, pins)
    assert "LABEL_TOO_CLOSE" in {v.code for v in legacy}, (
        "precondition: the historical attach ruler does fire here"
    )

    named = layout.validate_full(model, near, routes, pins, annotation_anchors=[])
    assert not {v.code for v in named if v.code.startswith("LABEL_")}, [
        v.render() for v in named
    ]


def test_the_solver_path_never_measures_the_router_attach_point(monkeypatch):
    """E2: ``generate_plan`` names its anchors on every page it tries."""
    seen: list[object] = []
    real = layout.validate_full

    def spy(*args, **kwargs):
        seen.append(kwargs.get("annotation_anchors", "<absent>"))
        return real(*args, **kwargs)

    monkeypatch.setattr(generate.layout, "validate_full", spy)
    model, offsets = _one_tall_part_net()
    generate.generate_plan(model, offsets)

    assert seen, "the solver never ran its self-check"
    for written in seen:
        assert written == [], (
            "a page-selection pass measured the attach fallback instead of "
            f"declaring its anchors: {written!r}"
        )


# --------------------------------------------------------------------------
# E3 — a name pressing a foreign net's wire is a blocking finding
# --------------------------------------------------------------------------


def _two_crossing_nets():
    """A's wire runs east; B's crosses it at A's own attach point."""
    model = DesignModel(
        components={
            "U1": Component(uid="u", designator="U1", pins=[
                Pin(number="1", name="1", net="A"),
            ]),
            "U2": Component(uid="u2", designator="U2", pins=[
                Pin(number="1", name="1", net="B"),
                Pin(number="2", name="2", net="B"),
            ]),
        },
        nets={
            "A": Net(name="A", pins=[("U1", "1")]),
            "B": Net(name="B", pins=[("U2", "1"), ("U2", "2")]),
        },
    )
    routes = [
        layout.RoutedNet(net="A", polylines=[[(0.0, 0.0), (100.0, 0.0)]], kind="port"),
        layout.RoutedNet(net="B", polylines=[[(50.0, -30.0), (50.0, 30.0)]], kind="port"),
    ]
    return model, routes


def test_a_name_drawn_across_a_foreign_wire_is_reported_and_blocks():
    """E3: the defect 岳 circled, finally measured by the terminal check."""
    model, routes = _two_crossing_nets()
    anchor = [("A", 50.0, 0.0)]  # A's own wire, and exactly where B crosses it

    hit = layout.annotation_anchor_violations(model, routes, [], anchor)
    assert [v.code for v in hit] == ["LABEL_ON_FOREIGN_WIRE"], [v.render() for v in hit]
    assert layout.blocking_violations(hit), "a name on a stranger's wire must block"

    # the same anchor off the crossing is clean: the ruler is about the wire
    clear = layout.annotation_anchor_violations(model, routes, [], [("A", 10.0, 0.0)])
    assert [v.code for v in clear] == [], [v.render() for v in clear]


def test_a_name_on_its_own_wire_is_never_a_foreign_wire_finding():
    """E3: its own net's wires are what the name is *supposed* to sit on."""
    model = DesignModel(
        components={
            "U1": Component(uid="u", designator="U1", pins=[
                Pin(number="1", name="1", net="A"),
            ]),
        },
        nets={"A": Net(name="A", pins=[("U1", "1")])},
    )
    routes = [
        layout.RoutedNet(
            net="A",
            polylines=[[(0.0, 0.0), (100.0, 0.0)], [(50.0, 0.0), (50.0, 40.0)]],
            kind="port",
        )
    ]
    hits = layout.annotation_anchor_violations(model, routes, [], [("A", 50.0, 0.0)])
    assert hits == [], [v.render() for v in hits]


def test_the_bar_is_contact_not_the_avoidance_search_s_margin():
    """E3: the terminal bar is "lies on the wire", not the search's 20 units.

    The margin is a *legibility* preference and belongs to the search, which can
    afford to insist; the check has to report a name that states a connection.
    Measured why this is not a taste: the human's own labels sit 10 units from
    foreign wires (the calibration behind ``WIRE_CLEARANCE``), and a terminal
    20-unit bar refused 31 of this repo's own draw-pipeline boards — see
    :func:`layout.annotation_anchor_violations`.
    """
    model = DesignModel(
        components={
            "U1": Component(uid="u", designator="U1", pins=[
                Pin(number="1", name="1", net="A"),
            ]),
        },
        nets={"A": Net(name="A", pins=[("U1", "1")])},
    )
    routes = [
        layout.RoutedNet(
            net="A", polylines=[[(0.0, 0.0), (500.0, 0.0)]], attach=(0.0, 0.0), kind="port",
        ),
        layout.RoutedNet(
            net="B", polylines=[[(700.0, -100.0), (700.0, 100.0)]], kind="port",
        ),
    ]
    half = max(layout.LABEL_MIN_TEXT_WIDTH, layout.LABEL_CHAR_WIDTH * len("A")) / 2.0

    def gate(anchor_x: float) -> list[layout.Violation]:
        return [
            v
            for v in layout.annotation_anchor_violations(
                model, routes, [], [("A", anchor_x, 0.0)]
            )
            if v.code == "LABEL_ON_FOREIGN_WIRE"
        ]

    assert gate(700.0 - half - 1.0) == [], "one unit short of the wire is readable, not a short"
    assert gate(700.0 - half + 1.0), "the box over the wire is reported"
    assert gate(700.0), "the box centred on the wire is reported"

    # and the search's own answer still survives the gate
    point, problem = layout.clear_label_point(routes, "A", [], {"U1"})
    assert point is not None and not problem, problem
    assert gate(point[0]) == [], (
        f"the search returned {point} and the gate reports it: the two rulers "
        "have drifted"
    )


# --------------------------------------------------------------------------
# E5 — a connected pin the plan cannot place is a blocking row
# --------------------------------------------------------------------------


def test_a_pin_the_plan_cannot_place_blocks_the_draw(monkeypatch):
    """E5: it was a note; a note is not a gate."""
    from boardwise.engines.draw import print_self_check

    model = DesignModel(
        components={
            "U": Component(uid="u", designator="U", pins=[
                Pin(number="1", name="1", net="SIG"),
                Pin(number="2", name="2", net="SIG"),
                Pin(number="3", name="3", net="SIG"),  # netlist member, no offset
            ]),
        },
        nets={"SIG": Net(name="SIG", pins=[("U", "1"), ("U", "2"), ("U", "3")])},
    )
    offsets = {"U": {"1": (0.0, 0.0), "2": (0.0, 30.0)}}
    plan = generate.generate_plan(model, offsets)

    assert ("U", "3") in plan.unplaced_pins
    row = [v for v in plan.violations if v.code == "PINS_UNPLACED"]
    assert row, [v.render() for v in plan.violations]
    assert "U.3" in row[0].subject
    assert layout.blocking_violations(row) == row, "the row must block"
    assert any("U.3" in line for line in print_self_check(plan)), print_self_check(plan)


def test_a_pin_left_open_on_purpose_is_not_a_pins_unplaced_row():
    """E5's boundary: ``nc_pins`` is a different state and stays a different one."""
    model = DesignModel(
        components={
            "U": Component(uid="u", designator="U", pins=[
                Pin(number="1", name="1", net="SIG"),
                Pin(number="2", name="2", net=None),  # declared NC, with an offset
                Pin(number="3", name="3", net=None),  # declared NC, *no* offset
            ]),
            "R": Component(uid="r", designator="R", pins=[
                Pin(number="1", name="1", net="SIG"),
            ]),
        },
        nets={"SIG": Net(name="SIG", pins=[("U", "1"), ("R", "1")])},
    )
    offsets = {"U": {"1": (0.0, 0.0), "2": (0.0, 30.0)}, "R": {"1": (200.0, 0.0)}}
    plan = generate.generate_plan(model, offsets)

    assert plan.unplaced_pins == [], plan.unplaced_pins
    assert {("U", "2"), ("U", "3")} <= set(plan.nc_pins)
    assert not [v for v in plan.violations if v.code == "PINS_UNPLACED"], [
        v.render() for v in plan.violations
    ]


# --------------------------------------------------------------------------
# E6 — two nets on one conductor is a short, not a spacing reading
# --------------------------------------------------------------------------


def _two_net_model() -> DesignModel:
    return DesignModel(
        components={
            "U1": Component(uid="u1", designator="U1", pins=[
                Pin(number="1", name="1", net="AAA"),
                Pin(number="2", name="2", net="AAA"),
            ]),
            "U2": Component(uid="u2", designator="U2", pins=[
                Pin(number="1", name="1", net="BBB"),
                Pin(number="2", name="2", net="BBB"),
            ]),
        },
        nets={
            "AAA": Net(name="AAA", pins=[("U1", "1"), ("U1", "2")]),
            "BBB": Net(name="BBB", pins=[("U2", "1"), ("U2", "2")]),
        },
    )


def test_two_nets_on_the_same_line_are_a_short_and_they_block():
    model = _two_net_model()
    routes = [
        layout.RoutedNet("AAA", [[(0.0, 0.0), (200.0, 0.0)]], attach=(0.0, 0.0), kind="port"),
        layout.RoutedNet("BBB", [[(40.0, 0.0), (160.0, 0.0)]], attach=(0.0, 0.0), kind="port"),
    ]
    violations = layout.validate_full(model, [], routes, {})
    codes = [v.code for v in violations]
    assert "WIRE_OVERLAP" in codes, codes
    assert "WIRE_TOO_CLOSE" not in codes, "a zero gap is not a spacing reading"
    overlap = [v for v in violations if v.code == "WIRE_OVERLAP"]
    assert layout.blocking_violations(overlap) == overlap
    assert "120 units" in overlap[0].detail


def test_a_merely_tight_pair_keeps_the_advisory_code():
    """E6: the upgrade is exactly the ``gap == 0`` shape and nothing wider."""
    model = _two_net_model()
    routes = [
        layout.RoutedNet("AAA", [[(0.0, 0.0), (200.0, 0.0)]], attach=(0.0, 0.0), kind="port"),
        layout.RoutedNet("BBB", [[(0.0, 5.0), (200.0, 5.0)]], attach=(0.0, 0.0), kind="port"),
    ]
    violations = layout.validate_full(model, [], routes, {})
    codes = [v.code for v in violations]
    assert "WIRE_TOO_CLOSE" in codes, codes
    assert "WIRE_OVERLAP" not in codes, codes
    assert layout.ADVISORY_VIOLATION_CODES == {"WIRE_TOO_CLOSE", "SEPARATION_GIVEN_UP"}


def test_two_vertical_nets_on_the_same_line_are_a_short_too():
    model = _two_net_model()
    routes = [
        layout.RoutedNet("AAA", [[(0.0, 0.0), (0.0, 200.0)]], attach=(0.0, 0.0), kind="port"),
        layout.RoutedNet("BBB", [[(0.0, 50.0), (0.0, 150.0)]], attach=(0.0, 0.0), kind="port"),
    ]
    codes = [v.code for v in layout.validate_full(model, [], routes, {})]
    assert "WIRE_OVERLAP" in codes, codes


# --------------------------------------------------------------------------
# E7 — one rule for "which side does this pin leave by"
# --------------------------------------------------------------------------


def _corner_pin_board():
    """Four pins on one part, one of them equidistant from W, E and N.

    Measured (163a): the router answers **E** for pin 2 — its W stub runs
    straight through pin 1's tip cell, so the tied W candidate is refused — while
    a bare ``min`` over the distance table (first of W, E, N, S) answers W.
    """
    pins = [
        Pin(number="1", name="1", net="N1"),
        Pin(number="2", name="2", net="N2"),
        Pin(number="3", name="3", net="N3"),
        Pin(number="4", name="4", net="N4"),
    ]
    model = DesignModel(
        components={"U": Component(uid="u", designator="U", pins=pins)},
        nets={
            pin.net: Net(name=pin.net, pins=[("U", pin.number)])
            for pin in pins
        },
    )
    offsets = {
        "U": {
            "1": (-35.0, 0.0),
            "2": (-25.0, 0.0),
            "3": (-15.0, -10.0),
            "4": (-20.0, 40.0),
        }
    }
    return model, offsets


def test_net_exits_leaves_by_the_side_the_router_leaves_by():
    """E7: the demand a gap is sized from is the demand the router creates."""
    model, offsets = _corner_pin_board()
    exits = layout.net_exits(model, offsets)
    rect = layout.Rect(*layout._relative_box(offsets["U"]))
    tips = offsets["U"]

    for number, tip in tips.items():
        siblings = [other for other in tips.values() if other != tip]
        router = layout._outward_direction(tip, rect, siblings)
        assert f"N{number}" in exits["U"][router], (
            f"pin {number} leaves by {router} (the router's answer) but net_exits "
            f"counted it on {[s for s in exits['U'] if f'N{number}' in exits['U'][s]]}"
        )


def test_net_exits_used_to_answer_with_a_bare_minimum():
    """E7's regression pin: the case must really be a tie the two rules split."""
    model, offsets = _corner_pin_board()
    rect = layout.Rect(*layout._relative_box(offsets["U"]))
    tip = offsets["U"]["2"]
    distances = {
        "W": tip[0] - rect.x0,
        "E": rect.x1 - tip[0],
        "N": tip[1] - rect.y0,
        "S": rect.y1 - tip[1],
    }
    minimum_first = min(distances, key=lambda side: distances[side])
    siblings = [other for other in offsets["U"].values() if other != tip]
    router = layout._outward_direction(tip, rect, siblings)

    assert minimum_first == "W", distances
    assert router == "E", distances
    assert "N2" in layout.net_exits(model, offsets)["U"]["E"]
